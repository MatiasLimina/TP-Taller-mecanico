# security-core Specification

## Purpose
Define las primitivas de seguridad del proceso: hashing y verificación de contraseñas sin bloquear el servidor, tokens de acceso firmados y transportados en cookie, y un hash ficticio que evita revelar qué cuentas existen.

## Requirements

### Requirement: Hash y verificación de contraseñas con bcrypt
El sistema SHALL calcular hashes de contraseña con bcrypt, sal aleatoria por hash y el costo configurado en `BCRYPT_COST`, y SHALL verificar una contraseña candidata contra el hash almacenado sin modificarlo. Un hash almacenado ilegible SHALL tratarse como verificación fallida y no como error del servidor.

#### Scenario: Hash verificable
- **WHEN** se calcula el hash de una contraseña y luego se verifica esa misma contraseña contra el hash
- **THEN** la verificación devuelve verdadero

#### Scenario: Contraseña incorrecta
- **WHEN** se verifica una contraseña distinta de la que originó el hash
- **THEN** la verificación devuelve falso

#### Scenario: Sal distinta por hash
- **WHEN** se calcula dos veces el hash de la misma contraseña
- **THEN** los dos hashes son distintos y ambos verifican la contraseña original

#### Scenario: Hash almacenado ilegible
- **WHEN** se verifica una contraseña contra un texto que no es un hash bcrypt válido
- **THEN** la verificación devuelve falso y no propaga un error

### Requirement: bcrypt fuera del bucle de eventos y con concurrencia acotada
El cálculo y la verificación de bcrypt SHALL ejecutarse fuera del bucle de eventos y con un máximo de `BCRYPT_MAX_CONCURRENCY` operaciones simultáneas por proceso. Las operaciones excedentes SHALL esperar su turno sin bloquear el bucle y sin fallar.

#### Scenario: El bucle sigue atendiendo
- **WHEN** se está calculando un hash bcrypt y en paralelo se ejecuta otra tarea asincrónica
- **THEN** la otra tarea avanza antes de que el hash termine

#### Scenario: Tope de concurrencia
- **WHEN** se inician ocho operaciones bcrypt simultáneas con `BCRYPT_MAX_CONCURRENCY=4`
- **THEN** nunca hay más de cuatro bcrypt en ejecución y las ocho terminan

#### Scenario: Las operaciones excedentes esperan
- **WHEN** se supera el tope de concurrencia
- **THEN** las operaciones adicionales esperan y completan, sin ser rechazadas

### Requirement: Límite de 72 bytes en contraseñas
Toda contraseña destinada a hash o verificación MUST medir como máximo 72 bytes en UTF-8. Una contraseña mayor SHALL rechazarse con un error propio antes de invocar bcrypt y MUST NOT truncarse a los primeros 72 bytes.

#### Scenario: Exactamente 72 bytes
- **WHEN** se hashea una contraseña de exactamente 72 bytes UTF-8
- **THEN** el hash se calcula y la contraseña verifica correctamente

#### Scenario: Un byte de más
- **WHEN** se intenta hashear una contraseña de 73 bytes UTF-8
- **THEN** se rechaza con un error propio y no se invoca bcrypt

#### Scenario: Pocos caracteres pero más de 72 bytes
- **WHEN** se intenta hashear una contraseña de 40 caracteres `ñ` (80 bytes UTF-8)
- **THEN** se rechaza con un error propio, porque el límite se mide en bytes y no en caracteres

#### Scenario: Sin truncamiento
- **WHEN** se intenta verificar una contraseña de 73 bytes cuyo primeros 72 bytes coinciden con una contraseña válida
- **THEN** se rechaza con un error propio y no se autentica con el prefijo

### Requirement: Emisión de token de acceso
El sistema SHALL emitir un JWT firmado con HS256 y `SECRET_KEY` cuyos claims incluyan `sub` con el id del usuario en texto, `iat` con fracción de segundo, `exp` igual a la marca de emisión más `ACCESS_TOKEN_EXPIRE_SECONDS`, y `roles` con los roles vigentes como dato informativo.

#### Scenario: Claims obligatorios
- **WHEN** se emite un token para un usuario con id 7 y roles `ADMIN` y `MECANICO`
- **THEN** el token contiene `sub` igual a `"7"`, `iat` numérico, `exp` numérico y `roles` con ambos roles

#### Scenario: Vigencia configurada
- **WHEN** se emite un token con `ACCESS_TOKEN_EXPIRE_SECONDS=1800`
- **THEN** `exp` equivale a la marca de emisión más 1800 segundos, redondeada al segundo

#### Scenario: Fracción de segundo en iat
- **WHEN** se emite un token con una marca de emisión que tiene microsegundos distintos de cero
- **THEN** al verificarlo, `iat` conserva esa fracción y no se trunca al segundo

#### Scenario: Roles informativos
- **WHEN** se emite un token con la lista de roles vigentes
- **THEN** el token incluye esos roles tal como se pasaron, sin consultar ni modificar la base

### Requirement: Verificación de token de acceso
Todo token SHALL verificarse con HS256 y `SECRET_KEY`. Un token con firma inválida o alterada, vencido, con claims obligatorios faltantes o con `sub` no numérico MUST rechazarse con un error propio que no revele el motivo ni el contenido del token.

#### Scenario: Token válido
- **WHEN** se verifica un token recién emitido y no vencido
- **THEN** se obtienen el id del usuario, la marca de emisión, la de vencimiento y los roles

#### Scenario: Token vencido
- **WHEN** se verifica un token cuyo `exp` ya pasó
- **THEN** se rechaza con el error propio de token inválido

#### Scenario: Firma alterada
- **WHEN** se modifica un carácter del token emitido
- **THEN** se rechaza con el error propio de token inválido

#### Scenario: Clave distinta
- **WHEN** se verifica con la aplicación un token firmado con otra clave
- **THEN** se rechaza con el error propio de token inválido

#### Scenario: Claims faltantes
- **WHEN** se verifica un token al que le falta `sub`, `iat` o `exp`
- **THEN** se rechaza con el error propio de token inválido

#### Scenario: sub no numérico
- **WHEN** se verifica un token cuyo `sub` es texto no convertible a entero
- **THEN** se rechaza con el error propio de token inválido

#### Scenario: Error sin detalles
- **WHEN** se rechaza un token
- **THEN** el mensaje de error es genérico y no incluye el token, la clave ni el motivo interno

### Requirement: Transporte del token en cookie HttpOnly
El token SHALL entregarse y borrarse únicamente mediante la cookie `access_token`, con `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` igual a la vigencia configurada y `Secure` según `COOKIE_SECURE`. El sistema MUST NOT devolver el token en el cuerpo ni aceptar `Authorization: Bearer` como autenticación.

#### Scenario: Atributos al emitir
- **WHEN** se entrega un token de acceso
- **THEN** la respuesta incluye `Set-Cookie: access_token=…` con `HttpOnly`, `SameSite=lax`, `Path=/` y `Max-Age` igual a `ACCESS_TOKEN_EXPIRE_SECONDS`

#### Scenario: Secure configurable
- **WHEN** `COOKIE_SECURE=true` o `COOKIE_SECURE=false`
- **THEN** la cookie incluye u omite el atributo `Secure` según ese valor

#### Scenario: Borrado de la cookie
- **WHEN** se cierra la sesión
- **THEN** la respuesta borra `access_token` con `Max-Age=0` y la cookie deja de enviarse

#### Scenario: Token fuera del cuerpo
- **WHEN** se responde a un login exitoso
- **THEN** el cuerpo no contiene el token ni la cookie

#### Scenario: Authorization ignorado
- **WHEN** una petición protegida presenta sólo `Authorization: Bearer` con un token válido y ninguna cookie
- **THEN** la petición se rechaza como no autenticada

### Requirement: Hash ficticio para anti-enumeración
La aplicación SHALL calcular una sola vez al arrancar un hash bcrypt de una contraseña aleatoria con el costo configurado y reutilizarlo mientras el proceso viva, de modo que el login de un correo inexistente ejecute el mismo trabajo bcrypt que el de una cuenta real.

#### Scenario: Disponible antes de atender
- **WHEN** el proceso termina de arrancar
- **THEN** el hash ficticio ya está calculado y listo para usarse

#### Scenario: Se reutiliza entre peticiones
- **WHEN** se atienden varios logins de correos inexistentes
- **THEN** se usa el mismo hash ficticio y no se recalcula por petición

#### Scenario: Verificación fallida
- **WHEN** se verifica cualquier contraseña candidata contra el hash ficticio
- **THEN** la verificación devuelve falso (salvo una coincidencia imposible con la contraseña aleatoria)

#### Scenario: Mismo costo que un hash real
- **WHEN** se compara el costo del hash ficticio con el de un hash de usuario
- **THEN** ambos usan el mismo `BCRYPT_COST`
