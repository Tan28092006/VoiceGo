# VoiceGo — Bảng phân rã công việc (Work Breakdown) · 3 Dev

> Chia cho **3 dev** theo domain để dễ giải trình "ai làm gì". Thay `Dev 1/2/3` bằng tên thật.
>
> - **Dev 1 — Backend AI/Voice/Location**: bộ não AI (agent), geocoding, định tuyến, STT/TTS, logic tiếp cận.
> - **Dev 2 — Backend Infra + Realtime + Driver + DevOps/Docs**: API/DB, socket realtime, màn tài xế, HTTPS/demo, tài liệu.
> - **Dev 3 — Frontend (Passenger app, Map, UI/UX)**: state, dịch vụ giọng nói FE, bản đồ, các màn UI, CSS/animation.

---

## 1. AI Agent & Hội thoại (backend/agent.py)
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 1.1 | Thiết kế `SYSTEM_PROMPT` (luật hỏi-lại khi mơ hồ, "xe máy hay ô tô", không mặc định) | agent.py | **Dev 1** |
| 1.2 | Khai báo bộ tool function-calling (`TOOLS`): resolve/select/quote/book/end | agent.py | **Dev 1** |
| 1.3 | Vòng điều phối tool `run_agent` (loop tối đa 6 lượt, ghép tool→ui) | agent.py | **Dev 1** |
| 1.4 | `_do_resolve` — gọi geocode + merge gazetteer, ra place/candidates | agent.py | **Dev 1** |
| 1.5 | `_do_select` — chọn ứng viên theo số thứ tự, kiểm tra cổng tiếp cận | agent.py | **Dev 1** |
| 1.6 | `_do_quote` — gọi định tuyến, dựng báo giá (km/phút/giá) | agent.py | **Dev 1** |
| 1.7 | `_do_book` — tạo chuyến đi | agent.py | **Dev 1** |
| 1.8 | `_apply_place_ui` — gắn kết quả lên UI, bỏ quote/candidates cũ khi đổi điểm | agent.py | **Dev 1** |
| 1.9 | `_clean_reply` — gộp câu trùng để đọc gọn | agent.py | **Dev 1** |
| 1.10 | `_say_money` — đọc tiền dạng "107 nghìn" | agent.py | **Dev 1** |
| 1.11 | `_picked_vehicle` — bắt "xe máy/ô tô", chặn đoán bừa | agent.py | **Dev 1** |
| 1.12 | `_chat_create` — auto-retry khi Groq 429 | agent.py | **Dev 1** |

## 2. Tính năng tiếp cận (Accessibility — Feature 2)
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 2.1 | Dữ liệu cổng tiếp cận `ACCESSIBLE_GATES` | agent.py | **Dev 1** |
| 2.2 | `_gates_for` / `_gate_candidates` — gợi ý cổng dễ tiếp cận | agent.py | **Dev 1** |
| 2.3 | Tô **xanh** điểm/cổng accessible trên bản đồ | MapView.jsx | **Dev 3** |
| 2.4 | Badge "♿ Điểm đến dễ tiếp cận" trên thẻ chuyến | TripInfo.jsx | **Dev 3** |
| 2.5 | Badge "♿ Chuyến chở người khuyết tật" + ghi chú cho tài xế | DriverView.jsx | **Dev 2** |
| 2.6 | Thu thập đánh giá mức độ tiếp cận (rating + lối vào) | RideArrived.jsx | **Dev 3** |

## 3. Geocoding chống hallucinate (backend)
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 3.1 | `geocode_candidates` — Nominatim/OSM trả nhiều kết quả | geocode.py | **Dev 1** |
| 3.2 | `HCMC_BOUNDS` + `_in_hcmc` + viewbox — chỉ lấy điểm TP.HCM | geocode.py | **Dev 1** |
| 3.3 | `_names_other_city` — từ chối tỉnh/thành khác | geocode.py | **Dev 1** |
| 3.4 | Gazetteer nội bộ + token matcher | places_db.py | **Dev 1** |
| 3.5 | District guard + precision-leftover guard | places_db.py | **Dev 1** |
| 3.6 | Dữ liệu địa điểm nhiều cơ sở (KHTN, Bách Khoa cs1/cs2) | places_db.py | **Dev 1** |

## 4. Định tuyến & báo giá (backend/routing.py)
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 4.1 | Gọi OSRM lấy quãng đường/thời gian/đường đi thật | routing.py | **Dev 1** |
| 4.2 | Công thức tính giá theo loại xe | routing.py | **Dev 1** |
| 4.3 | Trả geometry tuyến để vẽ bản đồ | routing.py | **Dev 1** |

## 5. Giọng nói — STT/TTS (backend/voice.py)
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 5.1 | Tích hợp FPT.AI ASR (chính) | voice.py | **Dev 1** |
| 5.2 | Tích hợp Groq Whisper (fallback): vi, temp=0, domain prompt | voice.py | **Dev 1** |
| 5.3 | Tham số chọn engine STT (fpt/whisper) | voice.py / main.py | **Dev 1** |
| 5.4 | Tích hợp FPT.AI TTS (giọng banmai) | voice.py | **Dev 1** |
| 5.5 | Đọc đúng loại xe trong câu TTS | voice.py | **Dev 1** |

## 6. API & Cơ sở dữ liệu (backend)
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 6.1 | Khởi tạo FastAPI + phục vụ `frontend/dist` | main.py | **Dev 2** |
| 6.2 | `/api/auth/login` — bcrypt, nhận diện vai trò | main.py | **Dev 2** |
| 6.3 | `/api/voice/stt` + `/api/voice/tts` | main.py | **Dev 2** |
| 6.4 | `/api/agent/chat` | main.py | **Dev 2** |
| 6.5 | `/api/voice/geocode` · `/api/rides` · `/api/reports` | main.py | **Dev 2** |
| 6.6 | `/api/health` (trạng thái Mongo) | main.py | **Dev 2** |
| 6.7 | Kết nối MongoDB + `mongo_status` | db.py | **Dev 2** |
| 6.8 | Seed user/tài xế/địa điểm/accessibility | seed_from_csv.py | **Dev 2** |

## 7. Frontend — Lõi app & state
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 7.1 | Định tuyến màn hình (Login → Home/Driver → Voice) | App.jsx | **Dev 3** |
| 7.2 | Reducer + state toàn cục, `RESET_TRIP` xoá atomic | AppContext.jsx | **Dev 3** |
| 7.3 | Hook `useVoiceApp` — vòng nghe (auto-listen, pause/resume) | useVoiceApp.js | **Dev 3** |
| 7.4 | `_send` — gọi agent, ghi đè destination/quote | useVoiceApp.js | **Dev 3** |
| 7.5 | Stream text từng chữ | useVoiceApp.js | **Dev 3** |
| 7.6 | Đồng bộ bộ nhớ hội thoại `messagesRef` | useVoiceApp.js | **Dev 3** |
| 7.7 | Reset/huỷ/quay-lại sạch state + ngắt socket | useVoiceApp.js / App.jsx | **Dev 3** |

## 8. Frontend — Dịch vụ giọng nói/HTTP
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 8.1 | Thu âm mic + phát hiện im lặng | voiceRecorder.js | **Dev 3** |
| 8.2 | TTS: 1 Audio bền + `genToken` (chỉ phát câu mới nhất) | tts.js | **Dev 3** |
| 8.3 | `unlockAudio` — mở khoá autoplay điện thoại | tts.js | **Dev 3** |
| 8.4 | Client API gọi backend | api.js | **Dev 3** |

## 9. Frontend — Bản đồ & màn chuyến đi
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 9.1 | Leaflet: ghim điểm đi/đến, vẽ tuyến, fitBounds | MapView.jsx | **Dev 3** |
| 9.2 | Marker ứng viên (đánh số) + tô xanh accessible | MapView.jsx | **Dev 3** |
| 9.3 | `invalidateSize` khi map co/giãn | MapView.jsx | **Dev 3** |
| 9.4 | Thẻ thông tin chuyến (giá/km/phút, chặn NaN) | TripInfo.jsx / TripCard.jsx | **Dev 3** |
| 9.5 | Màn "Đang di chuyển" (thu gọn/mở rộng) | RideMoving.jsx | **Dev 3** |
| 9.6 | Màn "Đã tới nơi" + đánh giá | RideArrived.jsx | **Dev 3** |
| 9.7 | Overlay tìm tài xế / PIN | TripOverlay.jsx | **Dev 3** |

## 10. Frontend — Giao diện trợ lý/giọng nói
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 10.1 | Sân khấu agent (text đang stream) | AgentStage.jsx | **Dev 3** |
| 10.2 | Overlay agent (popup) | AgentOverlay.jsx | **Dev 3** |
| 10.3 | Live transcript | LiveTranscript.jsx | **Dev 3** |
| 10.4 | Vùng cử chỉ xác nhận/huỷ | GestureZone.jsx | **Dev 3** |
| 10.5 | Nút mic tròn (FAB) | RecordButton.jsx | **Dev 3** |
| 10.6 | Header + nút quay lại | Header.jsx | **Dev 3** |
| 10.7 | ErrorBoundary | ErrorBoundary.jsx | **Dev 3** |

## 11. Trang chủ & Đăng nhập
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 11.1 | Trang chủ kiểu Grab (chọn xe, nút đặt giọng nói) | HomeView.jsx | **Dev 2** |
| 11.2 | Trang đăng nhập | LoginPage.jsx | **Dev 2** |

## 12. Realtime tài xế ↔ khách (Socket.IO)
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 12.1 | Client socket (kết nối, override `?realtime=`) | socket.js | **Dev 2** |
| 12.2 | Màn tài xế: idle→nhận→đến→PIN→hoàn thành | DriverView.jsx | **Dev 2** |
| 12.3 | Màn khách (tham khảo) | PassengerView.jsx | **Dev 2** |
| 12.4 | Luồng sự kiện realtime (waiting→accepted→arrived+PIN→verify→completed) | socket.js / useVoiceApp.js | **Dev 2** |
| 12.5 | Đọc PIN tự động 2 lần (guard `arrivedRef`) | useVoiceApp.js | **Dev 3** |
| 12.6 | Hợp đồng sự kiện realtime | REALTIME_INTEGRATION.md | **Dev 2** |

## 13. Mobile / HTTPS / Hạ tầng demo
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 13.1 | Vite HTTPS tự ký + host LAN + proxy | vite.config.js | **Dev 2** |
| 13.2 | Mở khoá audio + secure-context cho mic | tts.js / App.jsx | **Dev 3** |
| 13.3 | Hướng dẫn vào web qua cảnh báo chứng chỉ + cùng WiFi | DEMO.md | **Dev 2** |

## 14. Giao diện/UX (CSS & animation)
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 14.1 | Design tokens + global reset | tokens.css / global.css | **Dev 3** |
| 14.2 | CSS từng màn (Map, TripInfo, RideStatus, Agent, …) | styles/components/*.css | **Dev 3** |
| 14.3 | Animation co/giãn map, trượt overlay | VoiceScreen.css / *.css | **Dev 3** |

## 15. Tài liệu & Reproducibility (yêu cầu BTC)
| # | Đầu việc | File / vị trí | Người phụ trách |
|---|---|---|---|
| 15.1 | README (problem/solution/features) | README.md | **Dev 2** |
| 15.2 | Setup & Run | SETUP.md | **Dev 2** |
| 15.3 | Hướng dẫn sử dụng | USER_GUIDE.md | **Dev 2** |
| 15.4 | Tech stack & kiến trúc | ARCHITECTURE.md | **Dev 2** |
| 15.5 | Attribution & licensing + AI disclosure | ATTRIBUTION.md / LICENSE | **Dev 2** |
| 15.6 | Danh sách 50 địa điểm demo chuẩn | DEMO_DIADIEM.md | **Dev 2** |
| 15.7 | requirements.txt / package.json / .env.example | backend, frontend | **Dev 2** |

---

## Tổng kết phân chia (3 dev)
| Dev | Vai trò | Mảng phụ trách | Số đầu việc |
|---|---|---|---|
| **Dev 1** | Backend AI/Voice/Location | 1, 2.1–2.2, 3, 4, 5 | ~28 |
| **Dev 2** | Backend Infra + Realtime + Driver + DevOps/Docs | 6, 11, 12 (trừ 12.5), 13.1/13.3, 15, 2.5 | ~26 |
| **Dev 3** | Frontend Passenger app + Map + UI/UX | 7, 8, 9, 10, 14, 2.3/2.4/2.6, 12.5, 13.2 | ~30 |

> Lưu ý: Dev 3 (frontend) có số dòng nhiều hơn nhưng nhiều việc là CSS/UI nhỏ; Dev 2 ít dòng hơn nhưng gánh **tài liệu + realtime** (tốn công). Khối lượng thực tế khá cân.
