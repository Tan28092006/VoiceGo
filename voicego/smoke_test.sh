#!/usr/bin/env bash
# VoiceGo — kiểm tra nhanh sau khi deploy/khôi phục.
#   bash voicego/smoke_test.sh                       (mặc định: bản production)
#   bash voicego/smoke_test.sh http://localhost:8000 (bản chạy máy)
#
# Mục đích: bắt được lỗi "trang lên xanh nhưng app câm" — mọi API key đều mặc định
# rỗng, nên thiếu key thì server vẫn khởi động bình thường mà giọng nói không hoạt động.

set -u
BASE="${1:-https://voicego.onrender.com}"
PASS=0; FAIL=0

check() { # tên | mã mong đợi | đường dẫn
  local name="$1" want="$2" path="$3"
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 90 "$BASE$path")
  if [ "$code" = "$want" ]; then
    echo "  OK    $name ($code)"; PASS=$((PASS+1))
  else
    echo "  LỖI   $name — mong đợi $want, nhận $code"; FAIL=$((FAIL+1))
  fi
}

echo "Kiểm tra: $BASE"
echo

# 1. Còn bị Render treo không? Đây là thứ phải loại trừ trước tiên.
routing=$(curl -sI --max-time 90 "$BASE" | tr -d '\r' | awk -F': ' '/^x-render-routing/{print $2}')
if [ "$routing" = "suspend" ]; then
  echo "  DỪNG  Render vẫn đang treo service (x-render-routing: suspend)."
  echo "        Chưa gỡ suspend thì mọi kiểm tra bên dưới đều vô nghĩa."
  exit 1
fi

# 2. Server sống và phục vụ được frontend.
check "health"        200 "/api/health"
check "trang chủ"     200 "/"

# Body chứa tiếng Việt PHẢI gửi từ file, không nhúng thẳng vào dòng lệnh:
# Git Bash trên Windows làm hỏng UTF-8 khi truyền qua -d, server trả 400
# "error parsing the body" và trông y hệt như thiếu API key.
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
printf '%s' '{"text":"Xin chào, đây là kiểm tra giọng nói."}' > "$TMP/tts.json"
printf '%s' '{"messages":[{"role":"user","content":"Tôi muốn đi Chợ Bến Thành"}]}' > "$TMP/chat.json"

# 3. Giọng nói — phần dễ hỏng nhất, vì phụ thuộc key bên thứ ba.
echo
echo "TTS (đọc tiếng Việt):"
tts=$(curl -s -o /dev/null -w '%{http_code} %{size_download}' --max-time 90 \
      -X POST "$BASE/api/voice/tts" \
      -H 'Content-Type: application/json' \
      --data-binary @"$TMP/tts.json")
tts_code=${tts% *}; tts_size=${tts#* }
if [ "$tts_code" = "200" ] && [ "$tts_size" -gt 1000 ]; then
  echo "  OK    trả về audio ($tts_size bytes)"; PASS=$((PASS+1))
else
  # 502 = CẢ HAI engine cùng hỏng (FPT lẫn edge-tts). Hết quota FPT một mình
  # không đủ gây lỗi này — edge-tts không cần key nên lẽ ra phải đỡ được.
  echo "  LỖI   mã $tts_code, $tts_size bytes — cả FPT lẫn edge-tts đều hỏng;"
  echo "        kiểm tra edge-tts đã cài chưa (requirements.txt) và TTS_PRIMARY"; FAIL=$((FAIL+1))
fi

# 4. Agent + geocode — kiểm tra LLM key và dữ liệu địa điểm cùng lúc.
echo
echo "Agent (hội thoại + tìm địa điểm):"
reply=$(curl -s --max-time 180 -X POST "$BASE/api/agent/chat" \
        -H 'Content-Type: application/json' \
        --data-binary @"$TMP/chat.json")
if echo "$reply" | grep -qi 'bến thành'; then
  echo "  OK    agent nhận ra điểm đến"; PASS=$((PASS+1))
else
  echo "  LỖI   agent không phản hồi đúng — kiểm tra GROQ_API_KEY / MONGODB_URI"; FAIL=$((FAIL+1))
  echo "        trả về: $(echo "$reply" | head -c 300)"; FAIL=$((FAIL))
fi

echo
echo "─────────────────────────────"
echo "Đạt: $PASS   Hỏng: $FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo "Còn lỗi — KHÔNG gửi link cho ban giám khảo cho tới khi sạch."
  exit 1
fi
echo "Sạch. Vẫn nên tự nói thử một chuyến trên điện thoại trước khi nộp."
