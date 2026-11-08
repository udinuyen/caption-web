# Auto Caption Web — web nhận video, tự tạo phụ đề, gắn thẳng vào video

Tải video lên → AI (faster-whisper) nghe và chép lời → tạo phụ đề dễ đọc
(chữ trắng đậm trên nền đen, tối đa 2 dòng, nâng cao khỏi vùng nút bấm của
YouTube Shorts) → FFmpeg gắn phụ đề vào video → tải MP4 về đăng luôn.
Kèm theo file .SRT và .ASS để sửa chữ nếu Whisper nghe sai 1–2 từ.

## Vì sao deploy lên Render mà KHÔNG phải Vercel?

Vercel là serverless: mỗi request bị giết sau ~60 giây, không có FFmpeg
thường trực và không đủ RAM cho Whisper. Việc chép lời 1 video 1 phút đã
mất 1–3 phút CPU. Render chạy 1 container Docker thường trực nên làm được.
Chỉ cần **1 service duy nhất** trên Render (trang web + API chung 1 chỗ),
không cần Vercel nữa.

## Cách đưa lên Render (làm đúng thứ tự này)

1. Tạo 1 repo GitHub mới tên `caption-web` (giống cách bạn làm với
   StrangerChat), upload **toàn bộ** file trong thư mục/gói này lên repo,
   giữ nguyên cấu trúc (Dockerfile, render.yaml phải nằm ở thư mục gốc).
2. Vào https://dashboard.render.com → **New +** → **Blueprint**.
3. Chọn repo `caption-web` vừa tạo → Render tự đọc file `render.yaml`.
4. Bấm **Apply / Create**. Lần build đầu mất khoảng 10–20 phút vì phải
   tải sẵn model Whisper vào image — cứ để nó chạy, đừng bấm hủy.
5. Build xong, Render cho 1 địa chỉ dạng
   `https://caption-web-xxxx.onrender.com` — đó chính là web của bạn.
   Cần dùng thì mở địa chỉ đó, chọn video, bấm **Tạo phụ đề**, chờ, tải về.

## Chi phí — nói thẳng

- File `render.yaml` đang để gói **Starter ($7/tháng, 2 GB RAM)**. Đây là
  mức chạy được thật: model Whisper `base` + FFmpeg cần khoảng đó.
- Gói **Free của Render KHÔNG khuyên dùng** cho web này: chỉ 512 MB RAM
  (dễ bị giết giữa chừng khi chép lời), máy ngủ sau 15 phút không dùng và
  mất ~1 phút mới thức. Nếu vẫn muốn thử free: sửa `plan: starter` thành
  `plan: free` trong `render.yaml` và sửa biến `WHISPER_MODEL` thành
  `tiny` (nghe kém chính xác hơn, đặc biệt tiếng Việt).
- Muốn nghe chính xác hơn: đổi `WHISPER_MODEL` thành `small` trong
  Render → service → Environment (chậm hơn, tốn RAM hơn — nên đi cùng
  gói Standard).

## Chạy thử ngay trên máy Windows của bạn (không cần Render)

Nhấn đúp file `CHAY-LOCAL.bat`: lần đầu nó tự cài Python packages
(cần máy đã có Python và FFmpeg như pipeline OctopberAuto của bạn),
rồi mở web ở địa chỉ http://localhost:8000

## Giới hạn đã biết

- Tối đa 300 MB / video, xử lý **từng video một** (video thứ hai sẽ xếp
  hàng chờ) vì máy chủ chỉ có CPU.
- File kết quả tự xóa sau **1 giờ** — tải về ngay khi xong.
- Whisper nghe sai đôi khi ở tên riêng / số liệu; file .SRT đính kèm là
  để sửa nhanh những chỗ đó.
- Chưa có mật khẩu/màn hình đăng nhập: ai có link đều dùng được. Đừng
  chia sẻ link công khai; nếu cần khóa, báo để thêm mật khẩu đơn giản.

## Cấu trúc thư mục

```
caption-web/
├── Dockerfile        # image: python + ffmpeg + fonts + model Whisper
├── render.yaml       # cấu hình 1-click cho Render Blueprint
├── requirements.txt
├── app/
│   ├── main.py       # API: nhận upload, chạy job nền, cho tải file
│   └── caption.py    # Whisper -> ASS/SRT -> FFmpeg burn phụ đề
├── static/
│   └── index.html    # trang web tải video lên (tiếng Việt)
└── CHAY-LOCAL.bat    # chạy thử trên Windows
```
