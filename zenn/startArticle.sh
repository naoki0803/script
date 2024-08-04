#!/bin/bash

# Zennの作業ディレクトリを指定
ZENN_DIR="/Users/shiratorinaoki/zenn"

# VS Codeを開く
open -a "Visual Studio Code" "$ZENN_DIR"

# Zenn CLIプレビューを開始
(cd "$ZENN_DIR" && npx zenn preview &)

# 少し待機してからChromeを開く
sleep 3
open -a "Google Chrome" "http://localhost:8000"

# ウィンドウの配置を調整する（xdotoolを使用）
# VS CodeとChromeのウィンドウIDを取得する
CODE_WINDOW_ID=$(xdotool search --onlyvisible --name "Visual Studio Code" | head -n 1)
CHROME_WINDOW_ID=$(xdotool search --onlyvisible --name "Google Chrome" | head -n 1)

# ディスプレイの解像度を取得
SCREEN_WIDTH=$(xdpyinfo | awk '/dimensions/{print $2}' | cut -d 'x' -f 1)
SCREEN_HEIGHT=$(xdpyinfo | awk '/dimensions/{print $2}' | cut -d 'x' -f 2)
HALF_WIDTH=$((SCREEN_WIDTH / 2))

# VS Codeを左半分に配置
xdotool windowsize $CODE_WINDOW_ID $HALF_WIDTH $SCREEN_HEIGHT
xdotool windowmove $CODE_WINDOW_ID 0 0

# Chromeを右半分に配置
xdotool windowsize $CHROME_WINDOW_ID $HALF_WIDTH $SCREEN_HEIGHT
xdotool windowmove $CHROME_WINDOW_ID $HALF_WIDTH 0
