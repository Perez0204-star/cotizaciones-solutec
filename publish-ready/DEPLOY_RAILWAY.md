# Despliegue en Railway

Esta aplicacion ya queda preparada para publicarse en Railway usando el `Dockerfile` del proyecto.

## Antes de empezar

Necesitas:

- Una cuenta en Railway
- El codigo del proyecto en GitHub, GitLab o un repositorio que puedas subir

## Pasos recomendados

1. Sube este proyecto a un repositorio.
2. En Railway, crea un proyecto nuevo desde ese repositorio.
3. Railway detectara el `Dockerfile` automaticamente.
4. Crea un volumen persistente y montalo en:

```text
/app/data
```

Eso es importante porque la app guarda:

- la base SQLite
- logos
- archivos generados
- secreto de sesion local

5. Configura estas variables de entorno:

```text
SESSION_SECRET=pon-aqui-un-valor-largo-y-seguro
SESSION_HTTPS_ONLY=1
APP_DATA_DIR=/app/data
```

6. Configura el health check con esta ruta:

```text
/healthz
```

7. Despliega el servicio.

## Primer ingreso

Cuando el servicio quede arriba:

1. abre la URL publica que te entregue Railway
2. la app te llevara a `/setup`
3. crea el usuario administrador
4. luego podras entrar con `/login`

## Notas importantes

- Si cambias de servicio sin montar el mismo volumen, perderas la base SQLite.
- Para un uso empresarial mas fuerte, a futuro conviene mover la base a PostgreSQL.
- Mantener `SESSION_HTTPS_ONLY=1` es importante cuando la app este publicada con HTTPS.
