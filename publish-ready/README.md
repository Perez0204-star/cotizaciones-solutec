# Cotizaciones Web

Aplicacion en Python para administrar productos y servicios, crear cotizaciones, subir logo y exportar Excel o PDF con formato de plantilla.

## Incluye

- Catalogo de productos y servicios con modos de precio por margen, markup o manual.
- Gestion simple de clientes.
- Configuracion general de organizacion, prefijo, IVA, moneda y redondeo.
- Constructor de cotizaciones con calculo en tiempo real.
- Exportacion a Excel con plantilla, celdas combinadas, estilos y logo incrustado.
- Exportacion a PDF.
- Inicio de sesion con usuario y contrasena.
- Persistencia local con SQLite.

## Stack

- FastAPI
- Jinja2
- SQLite
- openpyxl
- Pillow

## Como ejecutar

```powershell
python -m pip install -r requirements.txt
python run.py
```

La aplicacion queda disponible en `http://127.0.0.1:8765` en el mismo equipo y en `http://IP-LOCAL:8765` dentro de la misma red.

## Primer acceso

La primera vez que abras la app, te llevara a `/setup` para crear el usuario administrador.

Recomendaciones:

- Usa un nombre de usuario simple, por ejemplo `admin_soluaec`
- Usa una contrasena de minimo 8 caracteres
- Guarda esas credenciales porque seran necesarias para entrar desde cualquier dispositivo

## Variables utiles para publicar

El servidor ya acepta host y puerto por entorno:

```powershell
$env:APP_HOST="0.0.0.0"
$env:APP_PORT="8765"
python run.py
```

En muchas plataformas de nube el puerto llega en la variable `PORT`, y `run.py` ya la soporta automaticamente.

Para cookies de sesion mas seguras en produccion con HTTPS:

```powershell
$env:SESSION_SECRET="cambia-esto-por-un-valor-largo-y-seguro"
$env:SESSION_HTTPS_ONLY="1"
python run.py
```

## Inicio rapido

Si quieres abrirla sin escribir comandos, haz doble clic en `iniciar_app.bat`.
Ese lanzador inicia el servidor local en segundo plano y abre la aplicacion en el navegador.

## Publicacion en internet

Para usarla desde cualquier dispositivo sin importar la red, todavia necesitas desplegarla en un servidor publico.

Opciones comunes:

- VPS con Windows o Linux
- Render
- Railway
- Azure App Service
- Google Cloud Run
- AWS Elastic Beanstalk o ECS

Antes de publicarla:

1. Crea el usuario administrador en `/setup`
2. Define `SESSION_SECRET`
3. Activa `SESSION_HTTPS_ONLY=1`
4. Publica detras de HTTPS
5. No compartas la base SQLite sin backups

## Verificacion rapida

1. Abre `/setup` y crea el usuario administrador
2. Inicia sesion en `/login`
3. Abre `/settings` y carga un logo
4. Crea productos o servicios en `/catalog`
5. Crea un cliente en `/clients`
6. Genera una cotizacion desde `/quotes/new`
7. Descarga el Excel desde el detalle de la cotizacion
