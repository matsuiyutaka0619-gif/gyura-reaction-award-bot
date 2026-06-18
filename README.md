# ギュラ鯖リアクション賞Bot

ギュラ鯖内で、前日20:45から当日20:44までにリアクションした人数が多かったメッセージTOP3を毎日発表するBotです。

無料運用を優先して、GitHub Actionsで毎日20:45頃に実行します。GitHub Actionsの定期実行は少し遅れることがあります。

## できること

- 毎日20:45頃に発表
- 集計範囲は前日20:45から当日20:44
- Botが読めるサーバー内テキストチャンネルを集計
- 除外チャンネルを設定可能
- Bot自身のメッセージは除外
- リアクションした人数が多いメッセージTOP3を発表
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
  "award_time": "20:45",
  "message_preview_length": 80
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
```

実際の投稿者はDiscordでメンション表示されるように `<@ユーザーID>` で投稿します。

## 手動テスト

GitHub ActionsのActionsタブから `Daily Reaction Award` を選び、`Run workflow` を押すと手動実行できます。

手動実行が成功する場合、Bot本体とWebhook設定は正常です。毎日の自動実行だけ遅れる場合は、GitHub Actionsのスケジュール遅延です。
