#!/usr/bin/env bash
# VoiceGo — đánh thức service Render Free trước giờ demo/chấm.
#   bash voicego/warmup.sh                          (mặc định: bản production)
#   bash voicego/warmup.sh https://voicego.res3pl.com
#
# Render Free ngủ sau 15 phút không có traffic, request đầu tiên chờ ~1 phút.
# Script này chịu cái chờ đó THAY CHO ban giám khảo.
#
# Chạy một lần rồi thoát, không phải uptime monitor -- vì thường chỉ cần đánh
# thức trước buổi demo là đủ. (Quota Free 750h/tháng tính cho CẢ WORKSPACE:
# 1 service thức cả tháng chỉ tốn 744h nên vẫn vừa, nhưng 2 service free cùng
# thức là 1488h -> cháy quota giữa tháng. Xem DEPLOY_DOMAIN.md Phần A.)

set -u
BASE="${1:-https://voicego.res3pl.com}"
DEADLINE=$((SECONDS + 180))

echo "Đánh thức: $BASE"
echo "(Render Free lạnh thì mất ~1 phút — cứ chờ.)"
echo

while :; do
  read -r code total < <(curl -s -o /dev/null \
      -w '%{http_code} %{time_total}\n' --max-time 90 "$BASE/api/health" || echo "000 0")

  if [ "$code" = "200" ]; then
    echo "  Đã thức — health 200 sau ${total}s."
    echo
    echo "Bước tiếp: bash voicego/smoke_test.sh $BASE   (phải đủ 4 OK)"
    exit 0
  fi

  # Hết quota thì đợi bao lâu cũng vô nghĩa — báo ngay, đừng để người dùng ngồi nhìn.
  if [ "$(curl -sI --max-time 30 "$BASE" | tr -d '\r' \
          | awk -F': ' '/^x-render-routing/{print $2}')" = "suspend" ]; then
    echo "  DỪNG  Render đang treo service (x-render-routing: suspend) — hết quota 750h."
    echo "        Đánh thức không cứu được. Xem voicego/RECOVERY.md, Kịch bản A."
    exit 1
  fi

  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    echo "  LỖI   quá 3 phút vẫn chưa lên (mã cuối: $code)."
    echo "        Không phải chuyện ngủ nữa — chẩn đoán theo voicego/RECOVERY.md, Bước 0."
    exit 1
  fi

  echo "  ...chưa lên (mã $code), thử lại sau 10s"
  sleep 10
done
