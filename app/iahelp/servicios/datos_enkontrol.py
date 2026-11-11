
# CATEGORÍAS PARA CLASIFICACIÓN DE INCIDENCIAS 


ENKONTROL_CATEGORIES = {
    
   
    
    "MÓDULO_OBRA": {
        "nombre": "Módulo de Obra",
        "descripcion": "Problemas relacionados con gestión de obra",
        "ejemplos": [
            "Avance de obra no se refleja",
            "Bitácora no guarda",
            "Bitácora no se visualiza",
            "Cronograma no actualiza",
            "Presupuesto vs real descuadrado",
            "No puedo capturar avance físico",
            "Partidas no aparecen",
            "Control de obra no funciona"
        ]
    },
    
    "MÓDULO_PRESUPUESTOS": {
        "nombre": "Presupuestos y Costos",
        "descripcion": "Problemas con presupuestos y control de costos",
        "ejemplos": [
            "Presupuesto no actualiza",
            "Costos descuadrados",
            "Desviaciones incorrectas",
            "No puedo modificar presupuesto",
            "Costos por partida erróneos",
            "Análisis de precios no carga"
        ]
    },
    
    "MÓDULO_INVENTARIOS": {
        "nombre": "Compras e Inventarios",
        "descripcion": "Problemas con materiales, almacén y compras",
        "ejemplos": [
            "Material no descarga de almacén",
            "Inventario descuadrado",
            "Entradas no registran",
            "Salidas no se guardan",
            "Comparativo de proveedores no funciona",
            "Requisición no se procesa",
            "Stock incorrecto"
        ]
    },
    
    "MÓDULO_FINANZAS": {
        "nombre": "Finanzas y Contabilidad",
        "descripcion": "Problemas financieros, contables y tesorería",
        "ejemplos": [
            "Pagos no reflejados",
            "Saldos incorrectos",
            "Facturas duplicadas",
            "Flujo de efectivo erróneo",
            "Tesorería descuadrada",
            "Cuentas por pagar incorrectas",
            "Cuentas por cobrar no actualizan",
            "Pólizas contables con error"
        ]
    },
    
    "MÓDULO_CRM": {
        "nombre": "CRM y Ventas",
        "descripcion": "Problemas con clientes y ventas",
        "ejemplos": [
            "Cliente no aparece",
            "Ventas no se registran",
            "Duplicidad de clientes",
            "Seguimiento de ventas no actualiza",
            "Cotizaciones no generan",
            "Contratos no se guardan"
        ]
    },
    
    "MÓDULO_MAQUINARIA": {
        "nombre": "Recursos y Maquinaria",
        "descripcion": "Problemas con control de maquinaria y equipos",
        "ejemplos": [
            "Uso de maquinaria no se registra",
            "Mantenimiento no guarda",
            "Combustible no descuenta",
            "Bitácora de equipo no funciona",
            "Horas máquina incorrectas"
        ]
    },
    
    "MÓDULO_REPORTES": {
        "nombre": "Reportes y Análisis",
        "descripcion": "Problemas con generación de reportes y BI",
        "ejemplos": [
            "Reporte no carga",
            "Reporte tarda mucho",
            "Datos desactualizados en reportes",
            "KPIs no calculan",
            "Exportación de reportes falla",
            "Dashboard no muestra información",
            "Gráficas no generan"
        ]
    },
    
    # ========== SISTEMA Y ACCESOS ==========
    
    "ACCESOS_PERMISOS": {
        "nombre": "Accesos y Permisos",
        "descripcion": "Problemas de autenticación, usuarios y permisos",
        "ejemplos": [
            "No puedo iniciar sesión",
            "Olvidé mi contraseña",
            "Usuario bloqueado",
            "No veo módulos",
            "No tengo permisos",
            "Sesión se cierra sola",
            "Credenciales no funcionan",
            "Solicitud de acceso a módulo nuevo",
            "Crear usuario nuevo"
        ]
    },
    
    "CONECTIVIDAD": {
        "nombre": "Conectividad y Comunicación",
        "descripcion": "Problemas de conexión con servidor remoto",
        "ejemplos": [
            "No conecta con servidor",
            "Error de conexión al abrir",
            "Timeout de conexión",
            "Datos no sincronizan",
            "Lentitud al guardar",
            "Se pierde la conexión",
            "Error al comunicarse con servidor"
        ]
    },
    
    "APLICACIÓN_WINDOWS": {
        "nombre": "Aplicación Windows",
        "descripcion": "Problemas con la aplicación de escritorio",
        "ejemplos": [
            "Aplicación no abre",
            "Enkontrol se cierra solo",
            "Pantalla en blanco",
            "Aplicación congelada",
            "Error al iniciar",
            "Aplicación crashea",
            "Necesita actualización",
            "Instalación corrupta",
            "Error de versión"
        ]
    },
    
    "SISTEMA_GENERAL": {
        "nombre": "Sistema General",
        "descripcion": "Problemas generales del sistema o servidor",
        "ejemplos": [
            "Sistema muy lento",
            "Servidor no responde",
            "Todos los usuarios afectados",
            "Enkontrol caído",
            "Error de servidor",
            "Base de datos inaccesible",
            "Sincronización entre módulos falla"
        ]
    },
    
    # ========== SOLICITUDES Y OTROS ==========
    
    "SOLICITUDES": {
        "nombre": "Solicitudes",
        "descripcion": "Peticiones de nuevos accesos, funcionalidades o capacitación",
        "ejemplos": [
            "Solicitud de acceso a módulo",
            "Solicitud de nuevo usuario",
            "Solicitud de permisos adicionales",
            "Capacitación en Enkontrol",
            "Consulta de funcionalidad",
            "Solicitud de mejora",
            "Duda de uso del sistema"
        ]
    },
    
    "HARDWARE_LOCAL": {
        "nombre": "Hardware Local",
        "descripcion": "Problemas de hardware de la PC donde corre Enkontrol",
        "ejemplos": [
            "PC muy lenta para Enkontrol",
            "Falta memoria RAM",
            "Disco lleno",
            "Problemas de monitor",
            "Impresora no imprime reportes"
        ]
    }
}


# CLASIFICACIÓN RÁPIDA POR PALABRAS CLAVE


CATEGORY_KEYWORDS = {
    "MÓDULO_OBRA": [
        "obra", "avance", "bitácora", "cronograma", "partida", 
        "presupuesto vs real", "control de obra", "físico", "planeado"
    ],
    
    "MÓDULO_PRESUPUESTOS": [
        "presupuesto", "costo", "desviación", "partida", 
        "análisis de precio", "precio unitario"
    ],
    
    "MÓDULO_INVENTARIOS": [
        "inventario", "almacén", "material", "stock", "entrada", 
        "salida", "descarga", "requisición", "proveedor", "compra"
    ],
    
    "MÓDULO_FINANZAS": [
        "pago", "factura", "tesorería", "flujo", "saldo", 
        "cuenta", "contable", "póliza", "cobrar", "pagar"
    ],
    
    "MÓDULO_CRM": [
        "cliente", "venta", "cotización", "contrato", 
        "seguimiento", "prospecto", "crm"
    ],
    
    "MÓDULO_MAQUINARIA": [
        "maquinaria", "equipo", "combustible", "mantenimiento", 
        "hora máquina", "recursos"
    ],
    
    "MÓDULO_REPORTES": [
        "reporte", "dashboard", "kpi", "gráfica", "exportar", 
        "análisis", "bi", "indicador"
    ],
    
    "ACCESOS_PERMISOS": [
        "contraseña", "login", "iniciar sesión", "usuario", 
        "permiso", "acceso", "bloqueado", "credencial"
    ],
    
    "CONECTIVIDAD": [
        "conexión", "servidor", "timeout", "sincroniza", 
        "no conecta", "error de conexión", "red"
    ],
    
    "APLICACIÓN_WINDOWS": [
        "no abre", "se cierra", "crashea", "congelada", 
        "instalación", "actualización", "versión", "app"
    ],
    
    "SISTEMA_GENERAL": [
        "lento", "caído", "todos", "servidor no responde", 
        "base de datos", "nadie puede"
    ],
    
    "SOLICITUDES": [
        "solicito", "necesito", "requiero", "capacitación", 
        "duda", "cómo", "consulta"
    ],
    
    "HARDWARE_LOCAL": [
        "pc lenta", "memoria", "disco", "monitor", "impresora"
    ]
}


# LISTADO SIMPLE DE CATEGORÍAS (para dropdowns o selección)


CATEGORIES_LIST = [
    "Módulo de Obra",
    "Presupuestos y Costos",
    "Compras e Inventarios",
    "Finanzas y Contabilidad",
    "CRM y Ventas",
    "Recursos y Maquinaria",
    "Reportes y Análisis",
    "Accesos y Permisos",
    "Conectividad",
    "Aplicación Windows",
    "Sistema General",
    "Solicitudes",
    "Hardware Local"
]


# FUNCIÓN DE AYUDA PARA CLASIFICACIÓN AUTOMÁTICA


def classify_category(ticket_description):
    """
    Clasifica automáticamente la categoría basándose en palabras clave.
    Retorna la categoría más probable.
    """
    description_lower = (ticket_description or "").lower()
    
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in description_lower)
        scores[category] = score
    
    # Retorna la categoría con mayor score
    if max(scores.values()) > 0:
        best_category = max(scores, key=scores.get)
        return ENKONTROL_CATEGORIES[best_category]["nombre"]
    
    return "Sistema General"  # Default si no encuentra coincidencias
  