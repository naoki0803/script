#!/bin/bash

# ポート8000が使用中か確認し、使用中であればそのプロセスを終了する
PORT=8000
PID=$(lsof -ti tcp:$PORT)

if [ ! -z "$PID" ]; then
    echo "Port $PORT is in use. Killing process $PID."
    kill -9 $PID
fi

# Zennのディレクトリに移動
cd $HOME/zenn

# Cursorでディレクトリを開く
open -a "Cursor" .

# Zennプレビューを実行する
npx zenn preview &

# 少し待つ
sleep 0.2

# プレビューURLをChromeで開く
open -na "Google Chrome" --args --new-window "http://localhost:8000"

# 解像度の変数を定義
# SCREEN_WIDTH=2560
# SCREEN_HEIGHT=1440

SCREEN_WIDTH=1470
SCREEN_HEIGHT=956

HALF_WIDTH=$((SCREEN_WIDTH / 2))

# AppleScriptを使ってウィンドウをタイル表示にする
osascript <<EOF

tell application "System Events"
    -- Cursorウィンドウを取得してサイズと位置を設定
    tell application "Cursor" to activate
    set cursorPosition to {0, 0}
    set cursorSize to {$HALF_WIDTH, $SCREEN_HEIGHT}
    try
        set position of window 1 of application process "Cursor" to cursorPosition
        set size of window 1 of application process "Cursor" to cursorSize
    on error
        log "Failed to set Cursor window position or size"
    end try

    -- Google Chromeウィンドウを取得してサイズと位置を設定
    tell application "Google Chrome" to activate
    set browserPosition to {$HALF_WIDTH, 0}
    set browserSize to {$HALF_WIDTH, $SCREEN_HEIGHT}
    
    -- すべての実行中のプロセスをループして、Chromeのウィンドウを見つける
    repeat with proc in (every process whose name is "Google Chrome")
        try
            set position of window 1 of proc to browserPosition
            set size of window 1 of proc to browserSize
            exit repeat
        on error
            -- エラーが発生した場合は次のプロセスに移動
        end try
    end repeat
end tell

-- 前面にアプリケーションを表示
tell application "Google Chrome" to activate
tell application "Cursor" to activate
EOF