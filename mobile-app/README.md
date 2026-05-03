# App movil con Capacitor

Este paquete convierte la plataforma web publicada en una aplicacion movil para Android e iOS usando Capacitor. La app movil abre tu sistema real por HTTPS, por lo que cualquier mejora que hagas en la web se refleja tambien en la app.

## Requisitos

- Node.js 20 o superior
- Android Studio para Android
- Xcode en macOS para iOS
- La web ya debe estar publicada con HTTPS y dominio propio

## Variables de entorno

Puedes copiar `.env.example` y usar estos valores:

- `MOBILE_APP_NAME`
- `MOBILE_APP_ID`
- `MOBILE_APP_URL`

Ejemplo en Windows PowerShell:

```powershell
$env:MOBILE_APP_NAME="Technological World"
$env:MOBILE_APP_ID="com.technologicalworld.comercial"
$env:MOBILE_APP_URL="https://tu-dominio.com/login"
```

## Instalacion base

```powershell
cd mobile-app
npm install
npm run sync
```

## Android

Primera vez:

```powershell
npm run add:android
```

Abrir en Android Studio:

```powershell
npm run open:android
```

Ejecutar en dispositivo o emulador:

```powershell
npm run run:android
```

Compilar binario:

```powershell
npm run build:android
```

Desde Android Studio puedes generar:

- APK para pruebas
- AAB para Google Play

## iOS

Primera vez:

```powershell
npm run add:ios
```

Abrir en Xcode:

```powershell
npm run open:ios
```

Ejecutar en simulador o dispositivo:

```powershell
npm run run:ios
```

Compilar binario:

```powershell
npm run build:ios
```

Importante:

- Para iOS necesitas macOS y Xcode.
- El archivo IPA se genera desde el proyecto nativo en Xcode o con el flujo de build configurado.

## Flujo recomendado

1. Publica la web con dominio y HTTPS.
2. Prueba que `https://tu-dominio.com/login` cargue bien.
3. Define `MOBILE_APP_URL` con esa URL.
4. Ejecuta `npm run sync`.
5. Agrega Android e iOS.
6. Prueba en Android Studio y Xcode.
7. Genera APK, AAB o IPA segun la plataforma.

## Notas tecnicas

- `webDir` apunta a una pagina minima de respaldo.
- La experiencia real usa `server.url` y carga tu sitio publicado.
- Si cambias el dominio, debes volver a sincronizar Capacitor.
