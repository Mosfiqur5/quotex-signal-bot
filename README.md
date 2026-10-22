# Quotex signal bot

Ei bot sudhu public market data dekhe Telegram ba console-e signal pathay. Eta kono auto-trade kore na; user nijey trade koren.

## Boro sabdhanota

Profit-er kono guarantee nei; binary options khub high risk ebong puro taka harate paren. 80% payout-e break-even win rate pray 55.6%. **Quotex OTC pair support nei**—OTC price sudhu Quotex-er vitore thake. Ekhankar real-market price-er sathe Quotex price ektu alada hote pare. Forex weekend-e bondho thake. Ei signal sudhu information, financial advice na.

Forex data Yahoo theke ashe, eta approximate (1m-e proti minute-e ekta price snapshot); tai forex signal o backtest Binance crypto data-r cheye kom reliable. Forex-er jonno `INTERVAL=5m` ebong `EXPIRY_MIN=5` recommend kori. Data weak hole backtest-e `WARNING` dekhabe.

## Shuru korun

1. Python 3.10 install korun.
2. Repo folder-e terminal khule `pip install -r requirements.txt` chalan.
3. Telegram-e `@BotFather` diye nijer bot banan, bot token nin.
4. Bot-ke ekta message pathan, tarpor browser-e `https://api.telegram.org/bot<TOKEN>/getUpdates` khule `chat`-er `id` dekhe nin.
5. `.env.example` copy kore `.env` nam din; token o chat ID boshan. Token kokhono karo sathe share korben na.
6. History test korte `python -m signalbot.backtest --pair EURUSD --days 5` chalan.
7. Signal bot chalu korte `python -m signalbot.main` chalan. Ekbar test korte `python -m signalbot.main --once` chalan. Telegram info na dile message console-e dekhabe.

## Settings

`.env`-e `PAIRS`, `INTERVAL` (`1m` ba `5m`), `EXPIRY_MIN`, `BB_PERIOD`, `BB_STD`, `RSI_PERIOD`, `RSI_LOW`, `RSI_HIGH`, `COOLDOWN_CANDLES`, `PAYOUT_PCT`, ebong `TIMEZONE` bodlate paren. `EXPIRY_MIN` interval-er gunito hote hobe.

## VPS e chalano

Ubuntu 22.04/24.04 VPS kinun, provider-er web console khulun, tarpor:

```bash
git clone https://github.com/Mosfiqur5/quotex-signal-bot.git
cd quotex-signal-bot
sudo bash install.sh
```

`.env` na thakle installer Telegram bot token o chat ID chaibe; token screen-e dekhabe na. Bot service chalu hole log dekhun `journalctl -u quotex-signal-bot -f` diye. Bondho/chalu/restart:

```bash
sudo systemctl stop quotex-signal-bot
sudo systemctl start quotex-signal-bot
sudo systemctl restart quotex-signal-bot
```

Settings bodlate `nano .env` chalan, tarpor `sudo systemctl restart quotex-signal-bot`. Update-er jonno `git pull && sudo systemctl restart quotex-signal-bot` chalan.
