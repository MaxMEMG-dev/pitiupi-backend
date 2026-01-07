# ============================================================
# database/services/register_service.py
# Servicio modular del registro PITIUPI v6
# Single Source of Truth - PostgreSQL
# MILESTONE #1 - VALIDACIONES COMPLETAS
# ============================================================

import re
from datetime import datetime
from sqlalchemy.orm import Session
from typing import Tuple, Optional


# ============================================================
# VALIDACIONES PURAS (NO DB, NO HTTP)
# ============================================================

def validate_name(name: str) -> Tuple[bool, Optional[str]]:
    """Valida nombre completo"""
    if not name or len(name.strip()) < 2:
        return False, "❌ El nombre debe tener al menos 2 caracteres."
    if not all(c.isalpha() or c.isspace() for c in name):
        return False, "❌ El nombre solo puede contener letras y espacios."
    return True, None


def validate_country(country: str) -> Tuple[bool, Optional[str]]:
    """Valida país"""
    if not country or len(country.strip()) < 2:
        return False, "❌ El país ingresado no es válido."
    return True, None


def validate_city(city: str) -> Tuple[bool, Optional[str]]:
    """Valida ciudad"""
    if not city or len(city.strip()) < 2:
        return False, "❌ La ciudad ingresada no es válida."
    return True, None


def validate_document(doc: str) -> Tuple[bool, Optional[str]]:
    """Valida documento de identidad (solo alfanuméricos)"""
    if not doc or len(doc.strip()) < 4:
        return False, "❌ Documento demasiado corto (mín. 4 caracteres)."
    if len(doc.strip()) > 20:
        return False, "❌ Documento demasiado largo (máx. 20 caracteres)."
    
    # Solo alfanuméricos (sin espacios ni símbolos)
    if not doc.strip().replace("-", "").isalnum():
        return False, "❌ Documento solo puede contener letras, números y guiones."
    
    return True, None


def validate_birthdate(date_str: str) -> Tuple[bool, Optional[str]]:
    """
    Valida fecha de nacimiento (YYYY-MM-DD).
    Requisito: Mínimo 12 años de edad.
    """
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        age = (datetime.now() - date).days // 365
        
        if age < 12:
            return False, "❌ Debes tener al menos 12 años para registrarte."
        if age > 120:
            return False, "❌ Fecha de nacimiento inválida."
        
        return True, None
    except ValueError:
        return False, "❌ Formato de fecha inválido. Usa: AAAA-MM-DD"


def validate_email(email: str) -> Tuple[bool, Optional[str]]:
    """
    Valida formato de email.
    Debe tener: usuario@dominio.extensión
    """
    email = email.strip().lower()
    
    # Patrón RFC 5322 simplificado
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    
    if not re.match(pattern, email):
        return False, "❌ Email inválido. Ejemplo: usuario@dominio.com"
    
    # Validaciones adicionales
    if len(email) < 5:
        return False, "❌ Email demasiado corto."
    if len(email) > 255:
        return False, "❌ Email demasiado largo."
    
    return True, None


def validate_phone(phone: str) -> Tuple[bool, Optional[str]]:
    """
    Valida número telefónico.
    Acepta: +593987654321, 0987654321, 987654321
    Solo números, espacios, guiones y símbolo +
    """
    # Limpiar espacios y guiones
    cleaned = re.sub(r"[\s\-()]", "", phone)
    
    # Debe empezar con + o ser solo dígitos
    if not cleaned.startswith("+"):
        if not cleaned.isdigit():
            return False, "❌ Teléfono debe contener solo números."
    else:
        # Si empieza con +, quitar el + y validar
        if not cleaned[1:].isdigit():
            return False, "❌ Teléfono con + debe tener solo números después."
    
    # Longitud
    digits_only = cleaned.lstrip("+")
    if len(digits_only) < 8:
        return False, "❌ Teléfono demasiado corto (mín. 8 dígitos)."
    if len(digits_only) > 15:
        return False, "❌ Teléfono demasiado largo (máx. 15 dígitos)."
    
    return True, None


# ============================================================
# GUARDAR REGISTRO PARCIAL (SYNC V6)
# ============================================================

def save_partial_registration(session: Session, telegram_id: str, **fields) -> None:
    """
    Guarda campos de registro parcial en PostgreSQL.
    SYNC - Compatible con arquitectura V6.
    
    Args:
        session: Sesión SQLAlchemy (debe venir del handler)
        telegram_id: ID de Telegram del usuario
        **fields: Campos a actualizar
    
    Campos permitidos:
        - telegram_first_name (nombre completo)
        - country
        - city
        - document_number
        - birthdate
        - email
        - phone
        - telegram_username
        - lang
    """
    from database.crud.user_crud import update_user_by_telegram_id
    
    # Normalizar campos
    allowed_fields = {
        "telegram_first_name", "country", "city", "document_number",
        "birthdate", "email", "phone", "telegram_username", "lang"
    }
    
    cleaned_fields = {}
    for key, value in fields.items():
        if key in allowed_fields and value is not None:
            # Normalizar strings
            if isinstance(value, str):
                cleaned_fields[key] = value.strip()
            else:
                cleaned_fields[key] = value
    
    if not cleaned_fields:
        return  # No hay nada que guardar
    
    # Actualizar en DB
    update_user_by_telegram_id(session, telegram_id, cleaned_fields)


# ============================================================
# VALIDACIÓN COMPLETA DEL PERFIL
# ============================================================

def is_profile_complete_for_registration(user) -> bool:
    """
    Valida si todos los campos obligatorios están completos.
    
    Campos requeridos:
        - telegram_first_name (nombre)
        - country
        - city
        - document_number
        - birthdate
        - email
        - phone
    
    Args:
        user: Objeto User de SQLAlchemy
    
    Returns:
        bool: True si todos los campos están completos
    """
    required_fields = [
        user.telegram_first_name,
        user.country,
        user.city,
        user.document_number,
        user.birthdate,
        user.email,
        user.phone,
    ]
    
    return all(
        field is not None and str(field).strip() != "" 
        for field in required_fields
    )


# ============================================================
# PREVIEW DEL PERFIL (FORMATEO)
# ============================================================

def get_registration_preview(user, lang: str = "es") -> str:
    """
    Genera vista previa del perfil para confirmación.
    Solo formateo de texto, NO toca DB.
    
    Args:
        user: Objeto User
        lang: Idioma ('es' o 'en')
    
    Returns:
        str: Texto formateado para mostrar
    """
    from i18n import t
    
    preview_lines = [
        f"🎉 <b>{t('onboarding.review_title', lang)}</b>\n"
    ]
    
    fields = [
        ("👤", t('onboarding.name', lang), user.telegram_first_name),
        ("🌍", t('onboarding.country', lang), user.country),
        ("🏙️", t('onboarding.city', lang), user.city),
        ("🪪", t('onboarding.document', lang), user.document_number),
        ("📅", t('onboarding.birthdate', lang), user.birthdate),
        ("📧", t('onboarding.email', lang), user.email),
        ("📱", t('onboarding.phone', lang), user.phone),
    ]
    
    for emoji, label, value in fields:
        if value:
            preview_lines.append(f"{emoji} <b>{label}:</b> {value}")
    
    return "\n".join(preview_lines)


# ============================================================
# UTILIDADES
# ============================================================

def format_birthdate_for_display(birthdate_str: str) -> str:
    """Formatea fecha YYYY-MM-DD a DD/MM/YYYY"""
    try:
        date = datetime.strptime(birthdate_str, "%Y-%m-%d")
        return date.strftime("%d/%m/%Y")
    except:
        return birthdate_str


def sanitize_user_input(text: str, max_length: int = 100) -> str:
    """Limpia y trunca entrada de usuario"""
    if not text:
        return ""
    
    # Eliminar espacios extra
    cleaned = ' '.join(text.split())
    
    # Truncar si es muy largo
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    
    return cleaned

