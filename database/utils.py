# ==========================================
# database/utils.py
# Utilidades universales para DB
# PITIUPI V6 — PostgreSQL únicamente
# ==========================================

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Union, Optional


# =====================================================
# FECHAS UTC
# =====================================================

def now_utc() -> datetime:
    """
    Retorna la fecha/hora actual en UTC con timezone-aware.
    
    Uso en modelos:
        created_at = Column(DateTime(timezone=True), default=now_utc)
    
    Uso en CRUD:
        transaction.completed_at = now_utc()
    
    Returns:
        datetime: Fecha/hora actual UTC con tzinfo
    """
    return datetime.now(timezone.utc)


# =====================================================
# OPERACIONES CON DECIMAL
# =====================================================

def to_decimal(value: Union[str, float, int, Decimal]) -> Decimal:
    """
    Normaliza cualquier valor numérico a Decimal con precisión 2 decimales.
    
    Seguro para operaciones financieras:
    - Evita errores de redondeo de float
    - Garantiza precisión en cálculos
    - Compatible con PostgreSQL NUMERIC
    
    Args:
        value: Número en cualquier formato
        
    Returns:
        Decimal: Valor normalizado a 2 decimales
        
    Examples:
        >>> to_decimal(10)
        Decimal('10.00')
        
        >>> to_decimal(10.555)
        Decimal('10.56')  # Redondeado
        
        >>> to_decimal("25.5")
        Decimal('25.50')
    """
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Convertir a string primero para evitar errores de float
    return Decimal(str(value)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )


def float_to_decimal(value: Union[float, str, int]) -> Decimal:
    """
    Alias explícito para to_decimal().
    
    Uso cuando la semántica es clara:
        amount = float_to_decimal(user_input)
    
    Args:
        value: Número a convertir
        
    Returns:
        Decimal: Valor normalizado a 2 decimales
    """
    return to_decimal(value)


def decimal_to_float(value: Optional[Decimal]) -> float:
    """
    Convierte Decimal → float de forma segura.
    
    Necesario para:
    - Serialización JSON (FastAPI responses)
    - APIs externas que no soportan Decimal
    - Logs legibles
    
    Args:
        value: Decimal o None
        
    Returns:
        float: Valor redondeado a 2 decimales, o 0.0 si None
        
    Examples:
        >>> decimal_to_float(Decimal("25.50"))
        25.5
        
        >>> decimal_to_float(None)
        0.0
    """
    if value is None:
        return 0.0
    
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# =====================================================
# UUID OPERATIONS
# =====================================================

def normalize_uuid(value: Union[str, uuid.UUID]) -> uuid.UUID:
    """
    Normaliza cualquier representación de UUID a objeto UUID.
    
    PostgreSQL almacena UUIDs nativamente, pero a veces llegan como strings
    desde APIs externas, forms, o JSON.
    
    Args:
        value: UUID como string o objeto UUID
        
    Returns:
        uuid.UUID: Objeto UUID validado
        
    Raises:
        ValueError: Si el string no es un UUID válido
        
    Examples:
        >>> normalize_uuid("550e8400-e29b-41d4-a716-446655440000")
        UUID('550e8400-e29b-41d4-a716-446655440000')
        
        >>> normalize_uuid(uuid.uuid4())
        UUID('...')  # Ya es UUID, retorna tal cual
    """
    if isinstance(value, uuid.UUID):
        return value
    
    # Intentar convertir string a UUID
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as e:
        raise ValueError(f"UUID inválido: {value}") from e


def generate_uuid() -> uuid.UUID:
    """
    Genera un nuevo UUID v4 aleatorio.
    
    Uso en servicios cuando se necesita UUID explícito:
        transaction_id = generate_uuid()
    
    Returns:
        uuid.UUID: Nuevo UUID v4
    """
    return uuid.uuid4()


# =====================================================
# JSON SERIALIZATION
# =====================================================

def json_safe(obj: Any) -> Any:
    """
    Convierte objetos complejos a tipos compatibles con JSON.
    
    Útil para:
    - Serializar respuestas FastAPI
    - Preparar datos para APIs externas
    - Logging estructurado
    
    Conversiones soportadas:
    - Decimal → float
    - datetime → ISO8601 string
    - UUID → string
    - dict/list → recursivo
    
    Args:
        obj: Objeto a convertir
        
    Returns:
        Any: Versión JSON-safe del objeto
        
    Examples:
        >>> json_safe(Decimal("25.50"))
        25.5
        
        >>> json_safe(datetime(2024, 1, 1, tzinfo=timezone.utc))
        '2024-01-01T00:00:00+00:00'
        
        >>> json_safe(uuid.uuid4())
        '550e8400-e29b-41d4-a716-446655440000'
        
        >>> json_safe({"amount": Decimal("100"), "id": uuid.uuid4()})
        {"amount": 100.0, "id": "550e8400-..."}
    """
    # Decimal → float
    if isinstance(obj, Decimal):
        return decimal_to_float(obj)

    # datetime → ISO8601
    if isinstance(obj, datetime):
        return obj.isoformat()

    # UUID → string
    if isinstance(obj, uuid.UUID):
        return str(obj)

    # dict → convertir recursivamente
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}

    # list/tuple → convertir recursivamente
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]

    # Otros tipos → retornar tal cual
    return obj


# =====================================================
# DICT UTILITIES
# =====================================================

def clean_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Elimina claves con valores None de un diccionario.
    
    Útil para:
    - Preparar payloads para APIs externas (Nuvei, etc)
    - Limpiar datos antes de insert/update
    - Evitar enviar campos opcionales vacíos
    
    Args:
        data: Diccionario a limpiar
        
    Returns:
        Dict: Nuevo diccionario sin claves None
        
    Examples:
        >>> clean_dict({"name": "Alice", "email": None, "age": 25})
        {"name": "Alice", "age": 25}
        
        >>> clean_dict({"a": 1, "b": None, "c": 0})
        {"a": 1, "c": 0}  # 0 se mantiene, solo None se elimina
    """
    return {k: v for k, v in data.items() if v is not None}


def merge_dicts(*dicts: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fusiona múltiples diccionarios (el último valor gana).
    
    Útil para:
    - Combinar configuraciones por defecto con custom
    - Merge de metadata
    
    Args:
        *dicts: Diccionarios a fusionar
        
    Returns:
        Dict: Diccionario fusionado
        
    Examples:
        >>> merge_dicts({"a": 1}, {"b": 2}, {"a": 3})
        {"a": 3, "b": 2}
    """
    result: Dict[str, Any] = {}
    for d in dicts:
        result.update(d)
    return result


# =====================================================
# EXPORTACIONES PÚBLICAS
# =====================================================

__all__ = [
    # Fechas
    "now_utc",
    
    # Decimales
    "to_decimal",
    "float_to_decimal",
    "decimal_to_float",
    
    # UUIDs
    "normalize_uuid",
    "generate_uuid",
    
    # JSON
    "json_safe",
    
    # Dicts
    "clean_dict",
    "merge_dicts",
]
