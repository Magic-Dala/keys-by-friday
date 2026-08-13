# Keys by Friday — 最簡單安裝與啟動方式

## 1. 安裝 Git 與 uv

開啟 PowerShell：

```powershell
winget install Git.Git
winget install --id=astral-sh.uv -e
```

## 2. 下載專案

```powershell
git clone -b feat/rental-agent-mvp https://github.com/Taoyuan-AI-Lab/keys-by-friday.git
cd keys-by-friday
```

## 3. 初始化環境與 API Key

進入專案目錄後直接執行：

```powershell
kbf init
```

不需要另外執行 `uv tool install`。

`kbf init` 會透過專案內建的 CLI 啟動環境初始化，並顯示 API Key 申請位置。

### Gemini API Key

前往：

```text
https://aistudio.google.com/app/apikey
```

登入 Google 帳號後建立 API Key，並複製保存。

### RealtyAPI Key

前往：

```text
https://www.realtyapi.io/
```

註冊帳號後，在 Dashboard 取得 API Key。

接著依 `kbf init` 提示輸入：

```text
Google / Gemini API key
RealtyAPI key
```

系統會自動建立 `.env`，不需要手動修改設定檔。

## 4. 啟動 Demo

目前啟動方式：

```powershell
uv run adk web . --no-reload --port 8765
```

瀏覽器打開：

```text
http://127.0.0.1:8765
```

選擇：

```text
rental_agent
```

完成。
