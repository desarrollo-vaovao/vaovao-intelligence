# Reportes por activo comercial

**Fecha:** 2026-08-20
**Estado:** aprobado, pendiente de plan de implementación

## Problema

Hoy el reporte se genera por **cliente**. El backend toma todas las cuentas
publicitarias registradas bajo ese cliente y arma un PDF multi-estación, con una
página por cuenta (`report_builder.build_report_data`, rama `len(accounts) > 1`).

Eso no corresponde a cómo se usa el sistema. Un "cliente" en la base es en
realidad un portafolio comercial, y sus activos comerciales pueden ser marcas
sin relación entre sí — en el caso de Vao Vao, una funeraria y una panadería
bajo el mismo portafolio. Enviar un solo PDF con los anuncios de ambas mezclados
no sirve para nadie.

El modo multi-estación nunca fue una función deseada: es un efecto secundario de
tener varios activos registrados bajo un mismo cliente.

Además, la etiqueta del activo se escribe a mano al registrarlo (`OLR_NETWORK`),
así que el nombre que se ve en la plataforma no coincide con el nombre real de
la cuenta en Meta (`OLR_C807 Network, S.A.`).

## Objetivo

Un reporte = un activo comercial. El activo se identifica en toda la plataforma
con su nombre real de Meta, heredado automáticamente al registrarlo.

## Diseño

### 1. El nombre del activo se hereda de Meta

`AdAccount.label` deja de ser un campo que el usuario escribe y pasa a ser un
espejo del nombre de la cuenta en Meta. El esquema de la base no cambia; cambia
quién lo llena.

**Registro — `POST /clients/{client_id}/ad-accounts`**

`AdAccountCreate` pierde el campo `label`. Queda `meta_ad_account_id` y
`recipient_emails`. Al guardar, la ruta:

1. Resuelve tokens con `_resolve_tokens` (helper que hoy vive en `reports.py`;
   se mueve a un módulo compartido para que `clients.py` pueda usarlo sin
   importar el módulo de reportes).
2. Llama `meta_api.check_account_access_with_fallback(tokens, id)`, que ya
   devuelve `(True, nombre)` o `(False, motivo)`.
3. Si `ok` → guarda con `label = nombre devuelto por Meta`.
4. Si no → responde **409** con el motivo tal cual lo dio Meta. No se guarda nada.

Registrar un activo lleva la verificación de acceso incorporada: para cuentas
nuevas, "Probar acceso" deja de ser un paso aparte.

**Edición — `PATCH /clients/{client_id}/ad-accounts/{account_id}`**

`label` sale de `AdAccountUpdate`; no se puede escribir por API. Si el PATCH
cambia `meta_ad_account_id`, el nombre se vuelve a resolver con la misma regla,
y si Meta no responde el cambio se rechaza con 409.

Se agrega `POST /clients/{client_id}/ad-accounts/{account_id}/refresh-name`,
para cuando renombren la cuenta en Meta. En la UI es un botón **"Actualizar
nombre"** por fila. No es automático: no queremos una llamada a Meta por cada
carga de la pantalla de Clientes.

**UI de Clientes**

- El formulario de nueva cuenta pide solo ID y correos.
- La columna "Etiqueta" pasa a llamarse "Activo comercial", muestra el nombre
  heredado en solo lectura, con una nota de que viene de Meta.
- Se quita el selector de `ClientType` (ver punto 2).

### 2. El reporte es de un activo comercial

**Selector (front).** El desplegable de Reportes lista activos comerciales, no
clientes: lista plana, ordenada alfabéticamente, sin agrupar por cliente. Como
el nombre viene de Meta, cada opción ya es distinguible por sí sola.

```
— Selecciona un activo comercial —
  C807 Operador Logístico
  CAM LOGISTICS, S.A. / POBOX
  Menos Pausa
  OLR_C807 Network, S.A.
  P.O Box
```

No existe forma de pedir "todos los activos de OLR de una vez". El cliente
sigue existiendo en la base como agrupación administrativa, pero no aparece en
Reportes.

No hace falta endpoint nuevo: `api.listClients()` ya devuelve cada cliente con
sus `ad_accounts`. El front aplana esa lista.

**Petición.** `ReportRequest.client_id` → `ad_account_id`. La ruta
`POST /reports/generate` valida que la cuenta sea de la organización del usuario
con el mismo join que ya usa `check-access`.

**Generación.** `build_report_data` y `build_pdf` reciben un `AdAccount` en vez
de un `Client`. Se elimina la rama multi-estación completa: el `if len(accounts)
> 1`, el `asyncio.gather` sobre cuentas, el reparto de presupuesto entre
estaciones y el `ValueError` de "el cliente no tiene cuentas registradas" (ya no
puede ocurrir). Queda un solo camino:

- un `get_account_data_with_fallback` sobre la cuenta elegida,
- el presupuesto completo aplicado a esa cuenta,
- `type: "single"` siempre.

`client_name` en los datos del PDF pasa a ser el nombre del activo. El archivo
queda `reporte-olr-c807-network-s-a-2026-08-16-a-2026-08-31.pdf`.

**Lo que se elimina.** El bloque `multi-station` de `pdf_generator`.
`ClientType.multi_station` queda sin uso: se retira de la UI y de
`ClientCreate`/`ClientUpdate`, pero el enum se deja en el modelo — borrarlo
exige una migración de base que no aporta nada ahora.

### 3. Cuentas ya registradas

Las cuentas existentes tienen etiquetas escritas a mano. Un script de un solo
uso (`scripts/backfill_ad_account_labels.py`) recorre cada `AdAccount`, pide el
nombre a Meta con los tokens centrales de su organización y reescribe `label`.
Las que no se resuelvan se dejan intactas y se listan al final, para revisarlas
a mano.

## Manejo de errores

| Situación | Respuesta |
|---|---|
| ID inválido o sin acceso al registrar | 409 con el motivo de Meta; no se guarda |
| Sin tokens de Meta al registrar | 503, mismo mensaje que hoy da `/reports/generate` |
| Activo borrado entre que se carga la lista y se genera | 404 "Activo comercial no encontrado" |
| Meta falla al actualizar el nombre | 409; el nombre anterior se conserva |

## Pruebas

- Registro de activo: con acceso guarda el nombre de Meta; sin acceso responde
  409 y no crea la fila.
- PATCH con `label` en el cuerpo: el campo se ignora (no está en el esquema).
- `build_report_data` sobre un `AdAccount`: devuelve `type: "single"` y el
  `client_name` del activo.
- `/reports/generate` con un `ad_account_id` de otra organización: 404.
- Front: el selector de Reportes muestra todos los activos de todos los
  clientes, plano y ordenado.

## Fuera de alcance

- Eliminar `ClientType` del modelo (requiere migración).
- Envío automático de reportes a `recipient_emails`.
- Refresco automático de nombres desde Meta.
