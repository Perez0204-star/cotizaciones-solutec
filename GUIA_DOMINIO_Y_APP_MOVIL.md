# Publicar online con dominio y convertir en app movil

## Resumen rapido

Este proyecto ya quedo preparado para:

- publicarse online con HTTPS
- usar dominio propio
- instalarse como PWA
- envolverse como app movil Android/iOS con Capacitor

## 1. Publicar la web con tu dominio

### Recomendado: Railway + dominio propio

Si ya tienes la app en Railway, el camino mas directo es este:

1. Sube la ultima version del proyecto a GitHub.
2. Railway detecta los cambios y redepliega.
3. En Railway abre el servicio web.
4. Ve a `Settings` -> `Networking` -> `Public Networking`.
5. Si aun no tienes dominio publico, usa `Generate Domain`.
6. Para tu dominio propio, agrega el `CNAME` y el `TXT` que Railway te entregue.
7. Espera la validacion y emision del SSL.
8. Comprueba que cargue:

```text
https://tu-dominio.com/login
```

### Importante sobre "gratis"

- Tu dominio normalmente no es gratis; debes comprarlo o ya tenerlo.
- Railway te da un dominio `railway.app`, pero el dominio propio depende de tu proveedor DNS.

### Opcion alternativa: Cloudflare Tunnel

Si quieres conservar SQLite local y evitar una migracion a base de datos cloud, puedes exponer tu equipo actual con Cloudflare Tunnel usando tu dominio. Eso si:

- el equipo debe quedar encendido
- la app debe estar corriendo siempre
- no es lo ideal para una operacion comercial de crecimiento

## 2. Convertir la web en app movil

La carpeta `mobile-app` ya esta lista para usar Capacitor con Android e iOS.

## Flujo correcto

1. Publica primero la web con dominio y HTTPS.
2. Define la URL publica:

```powershell
$env:MOBILE_APP_URL="https://tu-dominio.com/login"
```

3. Entra a `mobile-app` e instala:

```powershell
cd mobile-app
npm install
npm run sync
```

4. Genera proyecto Android:

```powershell
npm run add:android
npm run open:android
```

5. Genera proyecto iOS:

```powershell
npm run add:ios
npm run open:ios
```

## 3. Android

Desde Windows si puedes compilar Android usando Android Studio.

Pasos practicos:

1. Instala Android Studio.
2. Ejecuta `npm run open:android`.
3. Espera que Android Studio sincronice Gradle.
4. Prueba en emulador o telefono.
5. Genera:
   - APK para instalar manualmente
   - AAB para Google Play

## 4. iPhone / iPad

Para iOS necesitas:

- un Mac
- Xcode
- cuenta de Apple Developer si quieres distribuir formalmente

Pasos:

1. Lleva la carpeta del proyecto a un Mac.
2. En `mobile-app` ejecuta `npm install`.
3. Ejecuta `npm run add:ios`.
4. Ejecuta `npm run open:ios`.
5. Compila desde Xcode y genera el IPA o distribucion de App Store.

## 5. PWA ya lista

Ademas del contenedor movil, la web ya puede instalarse como app:

- Android: Chrome -> `Instalar app` o `Agregar a pantalla principal`
- iPhone: Safari -> `Compartir` -> `Anadir a pantalla de inicio`

## 6. Archivos clave ya preparados

- `app/static/service-worker.js`
- `app/templates/base.html`
- `mobile-app/capacitor.config.ts`
- `mobile-app/package.json`
- `mobile-app/.env.example`

## 7. Documentacion oficial

- Railway Public Networking: https://docs.railway.com/networking/public-networking
- Capacitor Installing: https://capacitorjs.com/docs/getting-started
- Capacitor Workflow: https://capacitorjs.com/docs/basics/workflow
