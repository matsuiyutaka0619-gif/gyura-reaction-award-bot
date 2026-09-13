# ギュラ鯖リアクション賞Bot

ギュラ鯖内で、当日5:00から翌日4:59までにリアクションした人数が多かったメッセージTOP5を毎日発表するBotです。

無料運用を優先して、GitHub Actionsで毎日5:00頃に実行します。GitHub Actionsの定期実行は少し遅れることがあります。

## できること

- 毎日5:00頃に発表
- 集計範囲は前日5:00から当日4:59
- Botが読めるサーバー内テキストチャンネル、スレッド、フォーラム投稿を集計
- 除外チャンネルを設定可能
- Bot自身のメッセージは除外
- リアクションした人数が多いメッセージTOP5を発表
- 同じ人が複数emojiでリアクションしても1人として集計
- 発表はDiscord Webhookに投稿

## 必要なDiscord権限

Botには以下の権限を付けてください。

- View Channels
- Read Message History

発表はWebhookで行うため、発表先チャンネルへのBotのSend権限は必須ではありません。

本文の一部を発表するため、Discord Developer Portalで以下もONにしてください。

- Message Content Intent

## セットアップ手順

### 1. Discord Botを作る

1. Discord Developer Portalを開く
2. New Applicationを押す
3. BotページでBotを作る
4. Tokenをコピーする
5. Privileged Gateway IntentsのMessage Content IntentをONにする

### 2. Botをサーバーに招待する

OAuth2 URL Generatorで以下を選びます。

- scopes: bot
- bot permissions: View Channels, Read Message History

作成されたURLを開いて、ギュラ鯖にBotを招待します。

### 3. 発表用Webhookを作る

1. 発表したいDiscordチャンネルを開く
2. チャンネル設定を開く
3. 連携サービスを開く
4. ウェブフックを作成
5. Webhook URLをコピーする

### 4. GitHub Secretsを登録する

GitHubのリポジトリで、Settings -> Secrets and variables -> Actions -> New repository secret から以下を登録します。

```text
DISCORD_BOT_TOKEN
DISCORD_WEBHOOK_URL
```

### 5. config.jsonを書く

`config.json` の `guild_id` を自分のサーバーIDに変更します。

```json
{
  "guild_id": "123456789012345678",
  "excluded_channel_ids": [
    "除外したいチャンネルID"
  ],
  "timezone": "Asia/Tokyo",
  "award_time": "05:00",
  "message_preview_length": 80,
  "award_limit": 5
}
```

除外チャンネルがない場合はこのままでOKです。

```json
"excluded_channel_ids": []
```

## 発表テキスト

```text
🏆 本日のギュラ鯖リアクション賞🏆 

🥇 1位
投稿者: @username
リアクション人数: 24

「今日の配信めちゃくちゃ良かった...」

元メッセージ:
https://discord.com/channels/...

🥈 2位
投稿者: @username
リアクション人数: 18

「次点のメッセージ...」

元メッセージ:
https://discord.com/channels/...

🥉 3位
投稿者: @username
リアクション人数: 12

「3位のメッセージ...」

元メッセージ:
https://discord.com/channels/...

4️⃣ 4位
（同じ形式で表示）

5️⃣ 5位
（同じ形式で表示）
```

実際の投稿者はDiscordでメンション表示されるように `<@ユーザーID>` で投稿します。

## 手動テスト

GitHub ActionsのActionsタブから `Daily Reaction Award` を選び、`Run workflow` を押すと手動実行できます。

手動実行が成功する場合、Bot本体とWebhook設定は正常です。毎日の自動実行だけ遅れる場合は、GitHub Actionsのスケジュール遅延です。

## フォーラムを含む集計範囲

通常のテキストチャンネルとアナウンスチャンネルに加え、Botから見える次の投稿も集計します。

- 公開スレッド
- アナウンスチャンネルのスレッド
- フォーラム投稿
- メディアチャンネルの投稿

実行時点でアクティブな投稿だけでなく、集計期間中にアーカイブされた公開投稿も取得します。非公開スレッドは、Botがそのスレッドを閲覧できる場合に限り対象になります。各親チャンネルで `View Channel` と `Read Message History` をBotに許可してください。
