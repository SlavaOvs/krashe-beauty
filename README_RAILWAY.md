# Beauty Booking – Railway Deployment

## Быстрый старт
```bash
npm i -g railway
railway login
cd beauty_booking_app
railway init        # Blank project
railway volume create data 1GB
railway up
```
В панели Railway:
* Variables → `PERSISTENT_DIR=/data`
* Settings → Deployments:
  * Install command: `pip install -r requirements.txt`
  * Start command: `uvicorn server:app --host 0.0.0.0 --port 10000`

Готово! Приложение будет доступно по URL вида https://<project>.railway.app