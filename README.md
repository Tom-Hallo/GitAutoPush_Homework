# GitPushManager

Desktop app (Windows, Python/PySide6) giúp sinh viên quản lý và push nhiều
bài tập GitHub cùng lúc mà không cần mở Terminal.

## Yêu cầu

- Windows 10/11
- Python 3.10+ (chỉ cần khi chạy từ source; bản `.exe` đã đóng gói sẵn không cần Python)
- **Git** đã cài và có trong PATH — app sẽ báo lỗi rõ ràng nếu thiếu, không crash
- GitHub Personal Access Token có scope `repo`

## Cài đặt (chạy từ source)

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python main.py
```

## Cấu trúc project

```
github_push_manager/
├── main.py                     # Entry point
├── requirements.txt
├── github_push_manager.spec    # PyInstaller spec -> dist\GitPushManager.exe
├── build_exe.bat                # Build 1-lệnh trên Windows
└── app/
    ├── db.py                    # SQLite: Project, Repository (+ migration an toàn)
    ├── github_client.py         # Token (keyring) + tạo repo qua PyGithub
    ├── git_ops.py                # git init/add/commit/push qua subprocess
    ├── naming.py                  # Sinh tên hàng loạt (Bai 1 / Bai_1 / bai-1 / bai1)
    ├── workers.py                 # QThread: verify token, tạo repo, push (1 hoặc tất cả)
    └── ui/
        ├── main_window.py         # Cửa sổ chính, layout, xử lý sự kiện
        ├── widgets.py              # ElidedLabel, StatusBadge, MultiCursorTextEdit,
        │                            DroppableRepoTable (Ctrl+D + drag&drop)
        └── dialogs.py               # Các dialog xác nhận (Push All, mismatch, conflict...)
```

## Tính năng

### GitHub Personal Access Token
- Nhập → **Lưu Token** (lưu bằng `keyring`, không lưu SQLite/JSON/txt/env,
  không log, không hiển thị token thật) → **Kiểm tra** (hiện GitHub username
  nếu hợp lệ) → **Xóa** (yêu cầu xác nhận).
- Mở lại app tự nhận biết token đã tồn tại.
- Token sai/hết hạn báo lỗi rõ ràng, không crash.

### Tạo hàng loạt repository
- Nhập tên bài + số lượng + format (`Bai 1` / `Bai_1` / `bai-1` / `bai1`).
- Nhấn Enter ở ô tên bài hoặc số lượng cũng tạo được (Enter không áp dụng
  cho các action nguy hiểm như Push All / Delete Project / Delete Token).
- Chạy nền (QThread), không block UI.
- **Chống trùng trong project**: tên đã có trong project (không phân biệt
  hoa/thường) sẽ tự động bị bỏ qua, có log cảnh báo, không tạo record trùng.
- **Repository đã tồn tại trên GitHub** (nhưng chưa có trong project): app
  hỏi **"Dùng Repository này"** hoặc **"Bỏ qua"** thay vì tự động dùng hay
  crash; nếu dùng, trạng thái ban đầu là `Not-UP` (không dùng "Existing"
  làm trạng thái chính).

### Bảng repository
Cột: `#`, `Repository`, `Folder`, `Commit Message`, `Branch`, `Status`,
`GitHub`, `Action`.

- Repository name và folder path dài được **elide ở giữa** (`D:\PTIT\...\Bai1`)
  kèm **tooltip hiển thị đầy đủ**; tự elide lại khi resize/maximize cửa sổ.
- Chưa gắn folder → hiện icon cảnh báo ⚠ bên cạnh, nhưng status vẫn là `Not-UP`.
- Status chỉ còn 4 giá trị: `Not-UP` (vàng), `Pushing...` (xanh dương,
  trạng thái trung gian), `Success` (xanh lá), `Failed` (đỏ) — hiển thị dạng
  badge/chip bo góc.
- Nút `GitHub ↗` mở repository bằng trình duyệt mặc định (dùng đúng
  `html_url` GitHub trả về, không tự đoán URL, không hard-code username).
- Nút `Push` có tooltip "Last push: dd/mm/yyyy HH:MM:SS" sau lần push thành công.
- Bảng dùng vertical scroll, header luôn cố định phía trên — thử với
  150+ repository vẫn mượt, không lag, không giới hạn số dòng.

### Kéo-thả nhiều folder (Drag & Drop)
Chọn nhiều folder trong Windows Explorer rồi kéo thả trực tiếp vào bảng:
- Số folder == số repository → tự động map toàn bộ theo thứ tự.
- Số folder ít hơn/nhiều hơn → hiện cảnh báo rõ số lượng, hỏi xác nhận
  trước khi map phần phù hợp; nếu **Hủy** thì giữ nguyên dữ liệu cũ.
- Mỗi mapping thành công được ghi vào Activity Log (`✓ Bai 1 ← D:\...`).

### Commit message + Ctrl+D multi-cursor
- Mỗi repository có commit message riêng, mặc định `Update <tên>`.
- Không được để trống khi Push (báo lỗi rõ ràng, không crash).
- Ô commit message hỗ trợ **Ctrl+D kiểu VS Code**: nhấn Ctrl+D để chọn từ
  dưới con trỏ, nhấn tiếp để chọn thêm occurrence kế tiếp, sau đó gõ để
  thay thế toàn bộ occurrence đang chọn cùng lúc. Không phá Ctrl+C/Ctrl+V/
  Ctrl+Z, không làm mất focus, Enter không tạo dòng mới và không kích hoạt
  push.

### Push từng repo / Push lại (re-push) / Push tất cả
- **Push 1 repo**: không cần confirm. Tự `git init` nếu chưa có `.git`, tự
  thêm/sửa `origin` nếu thiếu/sai, rồi `add` → `commit` → `push`. Không bao
  giờ re-init hay force-push nếu `.git` đã tồn tại — lịch sử commit cũ luôn
  được giữ nguyên.
- **Re-push**: sửa file trong folder rồi bấm Push lại — app tự commit +
  push tiếp, không tạo repo/`.git` mới, không mất commit cũ.
- **Không có thay đổi mới**: `git commit` báo "nothing to commit" **không
  bị coi là lỗi** — hiển thị "Không có thay đổi mới. Repository đã được
  cập nhật.", status vẫn `Success`, và vẫn thử `git push` phòng khi có
  commit local chưa được đẩy lên.
- **Push Tất Cả**: **luôn yêu cầu xác nhận** trước khi chạy (chỉ hành động
  này cần confirm). Chạy tuần tự trong background thread — GUI không bao
  giờ đơ. Một repository lỗi **không làm dừng** các repository còn lại.
  Có nút **Cancel** để dừng trước khi xử lý repository tiếp theo (không
  kill git đang chạy dở). Double-click Push All chỉ tạo đúng 1 worker;
  trong lúc Push All chạy, các nút Push từng dòng cũng bị khóa để tránh
  đụng độ.
- Đóng app trong lúc đang Push All sẽ hiện cảnh báo xác nhận trước.

### Project management
- New / Open (combo box) / Delete Project — Delete yêu cầu xác nhận.
- Mỗi project chứa nhiều repository; toàn bộ thay đổi (folder, commit
  message, status, last push...) được ghi vào SQLite ngay khi xảy ra.

### Database & migration
- SQLite tại `~/.github_push_manager/app.db` (Windows: dưới thư mục
  người dùng, ví dụ `C:\Users\<ten>\.github_push_manager\app.db`).
- Nâng cấp từ phiên bản cũ: **không xóa database cũ**, tự động
  `ALTER TABLE` thêm cột mới (`html_url`, `clone_url`) và gộp các status
  cũ (`Ready` / `Existing` / `No Folder`) về `Not-UP` — dữ liệu, project,
  repository đã lưu trước đó vẫn còn nguyên.

### Xử lý lỗi Git/GitHub
Phân loại thành thông báo thân thiện cho các trường hợp: thiếu Git/không
có trong PATH, folder không tồn tại/không phải thư mục, mất mạng, sai
token/hết hạn, permission denied, remote/repo không tồn tại, push
conflict (non-fast-forward), nothing to commit, timeout... Không bao giờ
hiện traceback thô cho người dùng thường — có nút **"Chi tiết lỗi"** để
xem kỹ thuật khi cần.

### Activity Log
Có timestamp + icon theo cấp độ (INFO `•` / SUCCESS `✓` / WARNING `⚠` /
ERROR `✗`). Không bao giờ log token, password, hay thông tin xác thực.

### Bảo mật
- Token **chỉ** nằm trong `keyring` (Windows Credential Manager) — không
  bao giờ ở SQLite/JSON/TXT/ENV, không log, không hiện trong dialog lỗi,
  không nhúng vào remote URL (`https://TOKEN@github.com/...`).

## Đóng gói thành `GitPushManager.exe` (Windows)

PyInstaller không cross-compile được từ Linux/Mac sang Windows, nên bước
build `.exe` phải chạy **trên máy Windows thật**:

```bat
build_exe.bat
```

Script sẽ tự động: tạo venv (nếu chưa có) → cài `requirements.txt` +
`pyinstaller` → build theo `github_push_manager.spec` → xuất ra
`dist\GitPushManager.exe` (single-file, `console=False` nên không mở cửa
sổ CMD đen).

Build thủ công nếu cần:

```bat
pip install -r requirements.txt pyinstaller
pyinstaller github_push_manager.spec
```

**Ghi chú:**
- Muốn icon riêng: đặt `app_icon.ico` vào thư mục gốc rồi bỏ comment dòng
  `icon='app_icon.ico'` trong `github_push_manager.spec`.
- Lần chạy `.exe` đầu tiên có thể bị Windows Defender/SmartScreen cảnh
  báo vì file chưa ký số — bình thường với app tự build bằng PyInstaller.
- `keyring` cần chạy trên Windows thật để dùng đúng Windows Credential
  Manager; test trên máy ảo/sandbox không có Credential Manager có thể
  khiến phần lưu token lỗi.
- `app.db` và token trong keyring nằm ở máy chạy `.exe`, không đóng gói
  kèm theo file `.exe`.

## Ghi chú môi trường kiểm thử

Toàn bộ logic (naming, git add/commit/push thật với local bare repo,
migration DB từ schema cũ, drag & drop mapping, Ctrl+D multi-select,
Push All confirm/cancel/double-click-guard, đóng app khi đang push...)
đã được kiểm thử tự động trong môi trường Linux không màn hình
(`QT_QPA_PLATFORM=offscreen`) vì môi trường phát triển không có Windows
hay mạng thật tới github.com — phần gọi GitHub API thật (`verify_token`,
`create_repository`) được test bằng cách giả lập (mock) phản hồi của
PyGithub. **Hãy chạy thử trực tiếp trên Windows với token GitHub thật**
trước khi dùng chính thức, đặc biệt là phần `keyring` (Windows Credential
Manager) và đường dẫn kiểu `D:\...`.
