## Cambios Principales Respecto a Versión Anterior

### Arquitectura

- **Antes**: Parking + Cabina (monolítico)
- **Ahora**: Parking + 3 Gestores especializados (modular)

### Concurrencia
- **Antes**: 1 entrada a la vez
- **Ahora**: 3 carriles simultáneos con locks ("esperas")

### Gestión de capacidad
- **Antes**: Rechazo directo si está lleno
- **Ahora**: Cola de espera + procesamiento automático

### Realismo
- **Antes**: Entradas/salidas aleatorias uniformes
- **Ahora**: Patrones horarios + duración estimada + salida ponderada

### Tipos de vehículos
- **Antes**: 2 tipos (normal, minusválido)
- **Ahora**: 4 tipos con tarifas diferenciadas

### Tipos de plazas
- **Antes**: Normal y minusválido
- **Ahora**: 3 tipos de parking + plazas eléctricas + minusválidos

### Interfaz
- **Antes**: Visualización básica
- **Ahora**: Dashboard completo con estadísticas en tiempo real y control de velocidad