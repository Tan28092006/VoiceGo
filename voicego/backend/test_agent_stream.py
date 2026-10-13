"""
test_agent_stream.py — Kiểm tra bản STREAM của agent (/api/agent/chat_stream) bằng LLM GIẢ,
không gọi mạng:
  - ReplySentenceStream nhả câu ngay khi câu trọn, và ghép lại ĐÚNG bằng _clean_reply (lời
    đáp của endpoint cũ) với mọi cách chia mẩu token;
  - _clean_reply sau khi tách _pre_clean vẫn y hệt bản cũ;
  - run_agent_stream: thứ tự sự kiện, tool_call ghép từ nhiều mẩu, câu đầu ra TRƯỚC khi
    LLM viết xong, lỗi giữa chừng vẫn trả lịch sử hợp lệ, client ngắt thì đóng stream LLM;
  - endpoint SSE: header chống đệm + định dạng sự kiện.

Chạy: cd voicego/backend && py -m pytest test_agent_stream.py -q
"""
import json
import random
import re
from types import SimpleNamespace as NS

import pytest

import agent
from agent import ReplySentenceStream, _clean_reply, run_agent_stream


# ── Bản _clean_reply TRƯỚC khi tách _pre_clean (chép nguyên từ commit f3c11fe) ──────
def _clean_reply_v0(text):
    if not text:
        return ""
    for marker in ("<function", "<tool_call", "<|python_tag|>", "```"):
        i = text.find(marker)
        if i != -1:
            text = text[:i]
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?m)^\s*#+\s*", "", text)
    text = agent._say_money(text)
    text = text.strip()
    parts = [p for p in re.split(r"(?<=[.?!…])\s+", text) if p.strip()]
    out = []
    for s in parts:
        if not out or s.strip().lower() != out[-1].strip().lower():
            out.append(s)
    return (" ".join(out).strip() or text)


SAMPLES = [
    "Mình tìm được rồi: Chợ Bến Thành, Công trường Quách Thị Trang, Quận 1. Bạn muốn đi xe máy hay ô tô?",
    "Từ chỗ bạn tới Chợ Bến Thành khoảng 8.5 ki-lô-mét, giá 92.000 đồng bằng xe máy. Bạn xác nhận đặt xe nhé?",
    "Được rồi. Được rồi. **Đại học Công nghiệp Hà Nội** có 3 cơ sở: một, 298 Cầu Diễn; hai, Tây Tựu; "
    "ba, Phủ Lý, Hà Nam. Bạn muốn đến cơ sở số mấy?",
    "## Kết quả\nGiá 107000 đồng!   Bạn đồng ý không… Mình chờ nhé.",
    "Tạm biệt bạn. <function=end_conversation>{}</function>",
    "Câu không có dấu chấm cuối",
    "   ",
    "Giá 1 250 000 đồng. Xe tới sau 4 phút. ```json {\"a\":1}```",
]


def _chunks(text, rng):
    i = 0
    while i < len(text):
        n = rng.randint(1, 6)
        yield text[i:i + n]
        i += n


@pytest.mark.parametrize("text", SAMPLES)
def test_clean_reply_unchanged(text):
    assert _clean_reply(text) == _clean_reply_v0(text)


@pytest.mark.parametrize("text", SAMPLES)
def test_sentences_join_to_clean_reply(text):
    for seed in range(25):
        rng = random.Random(seed)
        sp = ReplySentenceStream()
        got = []
        for c in _chunks(text, rng):
            got += sp.feed(c)
        rest, reply = sp.finish()
        got += rest
        assert reply == _clean_reply(text)
        assert " ".join(got) == reply, (seed, got)


def test_first_sentence_released_before_text_ends():
    text = SAMPLES[1]
    sp = ReplySentenceStream()
    first_at = None
    for k, ch in enumerate(text):           # từng ký tự một
        if sp.feed(ch) and first_at is None:
            first_at = k
    cut = text.index("xe máy. ") + len("xe máy. ")
    assert first_at == cut - 1               # nhả NGAY khi thấy khoảng trắng sau dấu chấm
    assert sp.emitted[0].startswith("Từ chỗ bạn") and "92 nghìn" in sp.emitted[0]


def test_decimal_point_is_not_a_sentence_end():
    sp = ReplySentenceStream()
    assert sp.feed("khoảng 8.") == []
    assert sp.feed("5 ki-lô-mét. ") == ["khoảng 8.5 ki-lô-mét."]


# ── LLM giả theo đúng dạng chunk của OpenAI SDK ──────────────────────────────────
def _content_chunk(s):
    return NS(choices=[NS(delta=NS(content=s, tool_calls=None))])


def _tool_chunk(index, id=None, name=None, args=None):
    tc = NS(index=index, id=id, function=NS(name=name, arguments=args))
    return NS(choices=[NS(delta=NS(content=None, tool_calls=[tc]))])


class FakeStream:
    def __init__(self, chunks, fail_after=None):
        self.chunks, self.fail_after = list(chunks), fail_after
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for c in self.chunks:
            if self.fail_after is not None and self.consumed >= self.fail_after:
                raise ConnectionError("mất kết nối giữa chừng")
            self.consumed += 1
            yield c

    def close(self):
        self.closed = True


class FakeClient:
    """Mỗi lần create(stream=True) trả stream kế tiếp trong kịch bản."""
    def __init__(self, streams):
        self.streams = list(streams)
        self.calls = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        assert kw.get("stream") is True
        self.calls.append([dict(m) for m in kw["messages"]])
        return self.streams.pop(0)


REPLY = "Mình tìm được rồi: Chợ Bến Thành, Quận 1. Bạn muốn đi xe máy hay ô tô?"


def _tool_round():
    return FakeStream([
        _tool_chunk(0, id="call_1", name="resolve_destination", args=""),
        _tool_chunk(0, args='{"query": "Chợ'),
        _tool_chunk(0, args=' Bến Thành"}'),
    ])


def _text_round(text=REPLY, **kw):
    return FakeStream([_content_chunk(c) for c in re.findall(r".{1,5}", text, re.S)], **kw)


@pytest.fixture
def fake_resolve(monkeypatch):
    seen = []

    def _do_resolve(query, pk):
        seen.append(query)
        return {"ok": True, "kind": "place", "name": "Chợ Bến Thành", "address": "Quận 1",
                "lat": 10.772, "lng": 106.698, "next": "Hỏi xe máy hay ô tô."}
    monkeypatch.setattr(agent, "_do_resolve", _do_resolve)
    return seen


def test_stream_turn_events(fake_resolve):
    text_round = _text_round()
    client = FakeClient([_tool_round(), text_round])
    events = []
    consumed_at_first_sentence = None
    for name, data in run_agent_stream([{"role": "user", "content": "cho mình đi chợ Bến Thành"}],
                                       None, client=client):
        if name == "sentence" and consumed_at_first_sentence is None:
            consumed_at_first_sentence = text_round.consumed
        events.append((name, data))

    names = [n for n, _ in events]
    assert names == ["tools", "sentence", "sentence", "done"]
    assert fake_resolve == ["Chợ Bến Thành"]               # args ghép đúng từ 3 mẩu
    # Câu 1 ra khi LLM mới viết được một phần lời đáp.
    assert consumed_at_first_sentence < len(text_round.chunks)

    tools = events[0][1]
    assert tools["ui"]["destination"]["name"] == "Chợ Bến Thành"
    roles = [m["role"] for m in tools["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert tools["messages"][2]["tool_calls"][0]["id"] == tools["messages"][3]["tool_call_id"] == "call_1"

    done = events[-1][1]
    sentences = [d["text"] for n, d in events if n == "sentence"]
    assert done["reply"] == " ".join(sentences) == _clean_reply(REPLY)
    assert done["messages"][:4] == tools["messages"]
    assert done["messages"][-1] == {"role": "assistant", "content": REPLY}
    assert done["ui"]["destination"]["lat"] == 10.772
    assert done["first_sentence_ms"] is not None
    # Vòng 2 gửi lên LLM có đủ kết quả tool của vòng 1.
    assert [m["role"] for m in client.calls[1]] == ["system", "user", "assistant", "tool"]


def test_stream_error_midway_keeps_valid_history(fake_resolve):
    # Vòng viết lời đứt sau khi đã nhả câu 1 -> lịch sử = mốc sau tool + đúng câu đã nghe.
    client = FakeClient([_tool_round(), _text_round(fail_after=12)])
    events = list(run_agent_stream([{"role": "user", "content": "đi chợ Bến Thành"}], None, client=client))
    done = events[-1][1]
    sentences = [d["text"] for n, d in events if n == "sentence"]
    assert sentences == ["Mình tìm được rồi: Chợ Bến Thành, Quận 1."]
    assert [m["role"] for m in done["messages"]] == ["system", "user", "assistant", "tool", "assistant"]
    assert done["messages"][-1]["content"] == sentences[0]
    assert done["ui"]["destination"]["name"] == "Chợ Bến Thành"


def test_stream_error_before_any_sentence():
    client = FakeClient([_text_round(fail_after=0)])
    msgs = [{"role": "user", "content": "alo"}]
    events = list(run_agent_stream(msgs, None, client=client))
    assert [n for n, _ in events] == ["sentence", "done"]
    assert events[-1][1]["messages"] == msgs                 # như run_agent cũ: giữ nguyên lịch sử
    assert "bận" in events[-1][1]["reply"]


def test_client_disconnect_closes_llm_stream(fake_resolve):
    text_round = _text_round()
    gen = run_agent_stream([{"role": "user", "content": "đi chợ Bến Thành"}], None,
                           client=FakeClient([_tool_round(), text_round]))
    for name, _ in gen:
        if name == "sentence":
            break
    gen.close()                                               # = client ngắt kết nối
    assert text_round.closed
    assert text_round.consumed < len(text_round.chunks)


def test_empty_reply_falls_back():
    client = FakeClient([FakeStream([_content_chunk("")])])
    events = list(run_agent_stream([{"role": "user", "content": "ừm"}], None, client=client))
    assert [d["text"] for n, d in events if n == "sentence"] == [agent._FALLBACK_EMPTY]
    assert events[-1][1]["reply"] == agent._FALLBACK_EMPTY


def test_sse_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import main

    def fake_stream(messages, pickup):
        yield "sentence", {"i": 0, "text": "Xin chào\nbạn.", "ms": 5}
        yield "done", {"reply": "Xin chào bạn.", "messages": messages, "ui": {}, "ms": 9,
                       "first_sentence_ms": 5}
    monkeypatch.setattr(agent, "run_agent_stream", fake_stream)
    c = TestClient(main.app)          # không dùng "with": khỏi chạy startup (warmup SDK)
    r = c.post("/api/agent/chat_stream", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-accel-buffering"] == "no"
    assert "no-cache" in r.headers["cache-control"]
    blocks = [b for b in r.text.split("\n\n") if b and not b.startswith(":")]
    evs = [(b.split("\n")[0][len("event: "):], json.loads(b.split("\n")[1][len("data: "):])) for b in blocks]
    assert evs[0] == ("sentence", {"i": 0, "text": "Xin chào\nbạn.", "ms": 5})
    assert evs[1][0] == "done" and evs[1][1]["reply"] == "Xin chào bạn."


# ── Thao tác ghi (book_ride): không báo "đã đặt" trước kết quả thật, không đặt 2 lần ──
def test_booking_claim_held_until_round_has_no_tool_calls(monkeypatch):
    # Vòng có lời dẫn "đã đặt xe" rồi mới gọi tool -> câu đó KHÔNG được nhả.
    monkeypatch.setattr(agent, "_book_once", lambda msgs, v, pk: {"ok": True, "kind": "booked", "rideId": "r1"})
    preamble_then_tool = FakeStream([
        _content_chunk("Mình đã đặt xe cho bạn rồi. "),
        _tool_chunk(0, id="b1", name="book_ride", args='{"vehicle":"bike"}'),
    ])
    final = _text_round("Đã đặt xe. Tài xế đang tới đón bạn.")
    events = list(run_agent_stream([{"role": "user", "content": "đặt đi"}], None,
                                   client=FakeClient([preamble_then_tool, final])))
    names = [n for n, _ in events]
    assert names == ["action", "tools", "sentence", "sentence", "done"]
    assert events[0][1]["name"] == "book_ride"
    texts = [d["text"] for n, d in events if n == "sentence"]
    assert texts == ["Đã đặt xe.", "Tài xế đang tới đón bạn."]      # chỉ sau khi tool đã trả kết quả
    assert "Mình đã đặt xe" not in " ".join(texts)


def test_booking_claim_without_tool_is_released_at_round_end():
    # Vòng cuối (không tool) có câu chứa "tài xế": vẫn đọc, chỉ là ra lúc hết vòng.
    client = FakeClient([_text_round("Bạn muốn đi xe máy hay ô tô? Tài xế sẽ gọi bạn.")])
    events = list(run_agent_stream([{"role": "user", "content": "ừ"}], None, client=client))
    assert [d["text"] for n, d in events if n == "sentence"] == ["Bạn muốn đi xe máy hay ô tô?", "Tài xế sẽ gọi bạn."]


class _FakeMsg:
    def __init__(self, content=None, tool_calls=None):
        self.content, self.tool_calls = content, tool_calls

    def model_dump(self, exclude_none=True):
        d = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            d["tool_calls"] = [{"id": t.id, "type": "function",
                                "function": {"name": t.function.name, "arguments": t.function.arguments}}
                               for t in self.tool_calls]
        return d


class FakeChatClient:
    """LLM giả KHÔNG stream cho run_agent (/api/agent/chat)."""
    def __init__(self, msgs):
        self.msgs = list(msgs)
        self.chat = NS(completions=NS(create=lambda **kw: NS(choices=[NS(message=self.msgs.pop(0))])))


def test_stream_dies_after_book_ride_then_fallback_books_once(monkeypatch):
    agent._BOOKED.clear()
    rides = []

    def fake_create_ride_request(**kw):
        rides.append(kw)
        return {"id": f"ride{len(rides)}", "driver": {}, "driver_user": {}}
    monkeypatch.setattr(agent, "create_ride_request", fake_create_ride_request)

    quote = {"ok": True, "kind": "quote", "name": "Chợ Bến Thành", "address": "Quận 1",
             "lat": 10.772, "lng": 106.698, "distanceKm": 20.1, "durationMin": 35,
             "priceVnd": 92000, "vehicle": "bike"}
    history = [
        {"role": "user", "content": "đi chợ Bến Thành, xe máy"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "q1", "type": "function", "function": {"name": "get_quote", "arguments": '{"vehicle":"bike"}'}}]},
        {"role": "tool", "tool_call_id": "q1", "content": json.dumps(quote, ensure_ascii=False)},
        {"role": "assistant", "content": "Giá 92 nghìn đồng bằng xe máy. Bạn xác nhận đặt xe nhé?"},
        {"role": "user", "content": "đồng ý"},
    ]
    book_round = FakeStream([_tool_chunk(0, id="b1", name="book_ride", args='{"vehicle":"bike"}')])
    gen = run_agent_stream(history, None, client=FakeClient([book_round, _text_round("Đã đặt xe.")]))
    seen = []
    for name, _ in gen:
        seen.append(name)
        if name == "tools":
            break
    gen.close()                     # stream chết NGAY sau khi book_ride đã chạy (client chưa thấy 'done')
    assert seen == ["action", "tools"] and len(rides) == 1

    # Client lùi về /api/agent/chat với CÙNG lịch sử (không biết lượt trước đã đặt xong).
    tc = NS(id="b2", function=NS(name="book_ride", arguments='{"vehicle":"bike"}'))
    monkeypatch.setattr(agent, "llm_client", lambda: FakeChatClient(
        [_FakeMsg(tool_calls=[tc]), _FakeMsg(content="Đã đặt xe cho bạn.")]))
    out = agent.run_agent(history, None)
    assert out["ui"]["booked"]["rideId"] == "ride1"     # trả lại ĐÚNG chuyến đã đặt
    assert len(rides) == 1                              # không tạo chuyến thứ hai

    # Một lượt MỚI (thêm tin nhắn user) vẫn đặt được chuyến mới.
    later = out["messages"] + [{"role": "user", "content": "đặt thêm một chuyến nữa"}]
    tc3 = NS(id="b3", function=NS(name="book_ride", arguments='{"vehicle":"bike"}'))
    monkeypatch.setattr(agent, "llm_client", lambda: FakeChatClient(
        [_FakeMsg(tool_calls=[tc3]), _FakeMsg(content="Đã đặt.")]))
    agent.run_agent(later, None)
    assert len(rides) == 2


# ── B2: lời mẫu cho kết quả tool sạch (bỏ vòng LLM thứ 2) ─────────────────────────
PLACE = {"ok": True, "kind": "place", "name": "Chợ Bến Thành",
         "address": "Chợ Bến Thành, Công trường Quách Thị Trang, Quận 1, 700000, Việt Nam",
         "lat": 10.77253, "lng": 106.69804}
HIST_PLACE = [
    {"role": "user", "content": "cho mình đi chợ Bến Thành"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "r1", "type": "function", "function": {"name": "resolve_destination", "arguments": '{"query":"Chợ Bến Thành"}'}}]},
    {"role": "tool", "tool_call_id": "r1", "content": json.dumps(PLACE, ensure_ascii=False)},
    {"role": "assistant", "content": "Mình tìm được rồi: Chợ Bến Thành, Quận 1. Bạn muốn đi xe máy hay ô tô?"},
    {"role": "user", "content": "đi xe máy"},
]
ROUTE = {"distanceKm": 20.1, "durationMin": 44, "geometry": [[1, 2]]}


class CountingChat:
    """LLM giả không stream, đếm số lần gọi."""
    def __init__(self, msgs):
        self.msgs, self.n = list(msgs), 0
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.n += 1
        return NS(choices=[NS(message=self.msgs.pop(0))])


def _tc(id, name, args):
    return NS(id=id, function=NS(name=name, arguments=args))


def _roles(msgs):
    return [m["role"] for m in msgs if m["role"] != "system"]


def test_clean_quote_skips_round_two(monkeypatch):
    monkeypatch.setattr(agent, "road_route", lambda *a: dict(ROUTE))
    fake = CountingChat([_FakeMsg(tool_calls=[_tc("q1", "get_quote", '{"vehicle":"bike"}')]),
                         _FakeMsg(content="KHÔNG được dùng")])
    monkeypatch.setattr(agent, "llm_client", lambda: fake)
    out = agent.run_agent(HIST_PLACE, None)
    assert fake.n == 1                                         # không có vòng LLM viết lời
    r = out["reply"]
    assert r == ("Từ chỗ bạn tới Chợ Bến Thành, Công trường Quách Thị Trang, Quận 1 khoảng 20 phẩy 1 "
                 "ki-lô-mét, đi mất chừng 44 phút, giá 92 nghìn đồng bằng xe máy. Bạn xác nhận đặt xe nhé?")
    assert "Việt Nam" not in r and "700000" not in r
    assert out["ui"]["quote"]["priceVnd"] == 92000 and out["ui"]["quote"]["geometry"] == [[1, 2]]
    # Lịch sử hợp lệ: assistant(tool_calls) -> tool -> assistant(lời mẫu)
    tail = out["messages"][-3:]
    assert [m["role"] for m in tail] == ["assistant", "tool", "assistant"]
    assert tail[0]["tool_calls"][0]["id"] == tail[1]["tool_call_id"] == "q1"
    assert tail[2] == {"role": "assistant", "content": r}


def test_clean_quote_stream_events(monkeypatch):
    monkeypatch.setattr(agent, "road_route", lambda *a: dict(ROUTE))
    client = FakeClient([FakeStream([_tool_chunk(0, id="q1", name="get_quote", args='{"vehicle":"car"}')])])
    hist = HIST_PLACE[:-1] + [{"role": "user", "content": "đi ô tô"}]
    events = list(run_agent_stream(hist, None, client=client))
    assert len(client.calls) == 1
    assert [n for n, _ in events] == ["tools", "sentence", "sentence", "done"]
    texts = [d["text"] for n, d in events if n == "sentence"]
    # ô tô: 29000 + 12000*20.1 = 270200 -> làm tròn 270 nghìn
    assert texts[0].endswith("giá 270 nghìn đồng bằng ô tô.") and "20 phẩy 1 ki-lô-mét" in texts[0]
    assert texts[1] == "Bạn xác nhận đặt xe nhé?"
    done = events[-1][1]
    assert done["reply"] == " ".join(texts)
    assert done["messages"][-1] == {"role": "assistant", "content": done["reply"]}
    assert done["messages"][:-1] == events[0][1]["messages"]   # mốc 'tools' + lời mẫu


@pytest.mark.parametrize("case", ["no_route", "need_vehicle", "candidates_after_place", "two_calls", "resolve"])
def test_unclean_results_still_use_round_two(monkeypatch, case):
    monkeypatch.setattr(agent, "road_route", (lambda *a: None) if case == "no_route" else (lambda *a: dict(ROUTE)))
    hist = list(HIST_PLACE)
    calls = [_tc("q1", "get_quote", '{"vehicle":"bike"}')]
    if case == "need_vehicle":
        hist[-1] = {"role": "user", "content": "đoán đi"}
    if case == "candidates_after_place":
        cands = {"ok": True, "kind": "candidates", "candidates": [{"name": "A"}, {"name": "B"}]}
        hist[-1:-1] = [{"role": "user", "content": "thôi đi đại học công nghiệp"},
                       {"role": "assistant", "content": "", "tool_calls": [
                           {"id": "r2", "type": "function", "function": {"name": "resolve_destination", "arguments": "{}"}}]},
                       {"role": "tool", "tool_call_id": "r2", "content": json.dumps(cands)},
                       {"role": "assistant", "content": "Có 2 cơ sở..."}]
    if case == "two_calls":
        calls.append(_tc("e1", "end_conversation", "{}"))
    if case == "resolve":
        monkeypatch.setattr(agent, "_do_resolve", lambda q, pk: {**PLACE})
        calls = [_tc("r9", "resolve_destination", '{"query":"Chợ Bến Thành"}')]
    fake = CountingChat([_FakeMsg(tool_calls=calls), _FakeMsg(content="Lời LLM viết.")])
    monkeypatch.setattr(agent, "llm_client", lambda: fake)
    out = agent.run_agent(hist, None)
    assert fake.n == 2 and out["reply"] == "Lời LLM viết."


def test_booking_template_only_when_saved(monkeypatch):
    agent._BOOKED.clear()
    quote = {"ok": True, "kind": "quote", "name": "Chợ Bến Thành", "address": "Quận 1", "lat": 10.77,
             "lng": 106.69, "distanceKm": 20.1, "durationMin": 44, "priceVnd": 92000, "vehicle": "bike"}
    hist = HIST_PLACE + [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "q1", "type": "function", "function": {"name": "get_quote", "arguments": '{"vehicle":"bike"}'}}]},
        {"role": "tool", "tool_call_id": "q1", "content": json.dumps(quote, ensure_ascii=False)},
        {"role": "assistant", "content": "Giá 92 nghìn đồng. Bạn xác nhận đặt xe nhé?"},
        {"role": "user", "content": "đồng ý"},
    ]
    rides = []
    monkeypatch.setattr(agent, "create_ride_request",
                        lambda **kw: rides.append(kw) or {"id": "ride1", "driver": {}, "driver_user": {}})
    client = FakeClient([FakeStream([_tool_chunk(0, id="b1", name="book_ride", args='{"vehicle":"bike"}')])])
    events = list(run_agent_stream(hist, None, client=client))
    assert len(client.calls) == 1 and len(rides) == 1
    assert [n for n, _ in events] == ["action", "tools", "sentence", "sentence", "done"]
    assert events[-1][1]["reply"] == agent.REPLY_TEMPLATES["booked"]
    assert events[-1][1]["ui"]["booked"]["dbSaved"] is True

    # Mongo hỏng (ok:true + tài xế giả + dbSaved:false) -> KHÔNG dùng mẫu, LLM viết như cũ.
    agent._BOOKED.clear()

    def boom(**kw):
        raise agent.MongoUnavailable("down")
    monkeypatch.setattr(agent, "create_ride_request", boom)
    client = FakeClient([FakeStream([_tool_chunk(0, id="b2", name="book_ride", args='{"vehicle":"bike"}')]),
                         _text_round("Mình chưa lưu được chuyến xe, bạn thử lại sau nhé.")])
    events = list(run_agent_stream(hist, None, client=client))
    assert len(client.calls) == 2
    assert events[-1][1]["ui"]["booked"]["dbSaved"] is False
    assert events[-1][1]["reply"] != agent.REPLY_TEMPLATES["booked"]


def test_say_helpers():
    assert agent._say_km(8.0) == "8 ki-lô-mét"
    assert agent._say_km(20.14) == "20 phẩy 1 ki-lô-mét"
    assert agent._say_km(0.84) == "850 mét"
    assert agent._say_dest("Landmark 81", "720A Điện Biên Phủ, Bình Thạnh, Việt Nam") == "Landmark 81, 720A Điện Biên Phủ, Bình Thạnh"
