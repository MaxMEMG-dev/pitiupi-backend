# ============================================================
# handlers/user/deposit.py — PITIUPI V7.1 (Stripe Web Integration)
# ✅ URL Fix: Asegura parámetros userId y amount
# ============================================================

import os
import logging
import time
import stripe
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.session import SessionLocal
from database.services.users_service import get_user_by_telegram_id
from i18n import t

deposit_router = Router()
logger = logging.getLogger(__name__)


STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logger.warning("⚠️ STRIPE_SECRET_KEY no configurada. Los pagos no funcionarán.")

# ============================================================
# CONFIGURACIÓN
# ============================================================

# IMPORTANTE: Asegúrate de que esta URL sea la final (con https y www si aplica)
# Si tu página es https://pitiupi.com/checkout, pon esa.
# Si usas www, pon https://www.pitiupi.com/checkout/
BASE_CHECKOUT_URL = "https://www.pitiupi.com/checkout/"

QUICK_AMOUNTS = [5, 10, 20, 50, 100]
MIN_DEPOSIT = 5.00
MAX_DEPOSIT = 1000.00

# ============================================================
# FSM
# ============================================================

class DepositStates(StatesGroup):
    WAITING_CUSTOM_AMOUNT = State()

# ============================================================
# VALIDACIONES
# ============================================================

def validate_deposit_amount(amount_str: str) -> tuple[bool, str, float]:
    try:
        amount = float(amount_str.replace(",", ".").replace("$", "").strip())
        if amount < MIN_DEPOSIT:
            return False, f"❌ Monto mínimo: ${MIN_DEPOSIT}", 0.0
        if amount > MAX_DEPOSIT:
            return False, f"❌ Monto máximo: ${MAX_DEPOSIT}", 0.0
        return True, "", amount
    except ValueError:
        return False, "❌ Monto inválido. Usa números (ej: 10.00)", 0.0

# ============================================================
# COMANDO: /depositar
# ============================================================

@deposit_router.message(Command("depositar"))
@deposit_router.message(F.text.in_({
    "➕ Depositar", "💰 Depositar", "Depositar", "➕ Deposit", "Deposit",
    t("menu.deposit", "es"), t("menu.deposit", "en")
}))
async def cmd_deposit(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)
    session = SessionLocal()
    try:
        user = get_user_by_telegram_id(session, telegram_id)
        if not user:
            await message.answer("⚠️ Usuario no encontrado. Usa /start.")
            return
        
        lang = user.lang or "es"
        # Opcional: Validar KYC aquí si es necesario
        
        await show_deposit_menu(message, lang)
    except Exception as e:
        logger.error(f"❌ Error en cmd_deposit: {e}", exc_info=True)
        await message.answer("❌ Error interno. Intenta nuevamente.")
    finally:
        session.close()

async def show_deposit_menu(message: Message, lang: str = "es"):
    quick_buttons = []
    row = []
    for amt in QUICK_AMOUNTS:
        row.append(InlineKeyboardButton(text=f"${amt}", callback_data=f"deposit:amount:{amt}"))
        if len(row) == 3:
            quick_buttons.append(row)
            row = []
    if row:
        quick_buttons.append(row)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        *quick_buttons,
        [InlineKeyboardButton(text=f"⌨️ {t('deposit.custom_amount', lang)}", callback_data="deposit:custom")],
        [InlineKeyboardButton(text=f"🔙 {t('common.back', lang)}", callback_data="menu:main")]
    ])
    
    await message.answer(
        f"💳 <b>{t('deposit.title', lang)}</b>\n\nSelecciona el monto a recargar:",
        reply_markup=kb,
        parse_mode="HTML"
    )

# ============================================================
# HANDLERS
# ============================================================

@deposit_router.callback_query(F.data.startswith("deposit:amount:"))
async def handle_quick_amount(callback: CallbackQuery):
    amount_str = callback.data.split(":")[-1]
    telegram_id = str(callback.from_user.id)
    try:
        amount = float(amount_str)
        await callback.answer()
        await process_deposit_redirect(callback.message, telegram_id, amount)
    except ValueError:
        await callback.answer("⚠️ Error en el monto", show_alert=True)

@deposit_router.callback_query(F.data == "deposit:custom")
async def handle_custom_amount(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        "💰 <b>Monto Personalizado</b>\n\nEscribe la cantidad (Ej: 15.50):",
        parse_mode="HTML"
    )
    await state.set_state(DepositStates.WAITING_CUSTOM_AMOUNT)

@deposit_router.message(DepositStates.WAITING_CUSTOM_AMOUNT)
async def receive_custom_amount(message: Message, state: FSMContext):
    is_valid, error_msg, amount = validate_deposit_amount(message.text)
    if not is_valid:
        await message.answer(error_msg)
        return
    await state.clear()
    telegram_id = str(message.from_user.id)
    await process_deposit_redirect(message, telegram_id, amount)

# ============================================================
# LÓGICA REDIRECCIÓN (Core Fix)
# ============================================================

async def process_deposit_redirect(message: Message, telegram_id: str, amount: float):
    """
    ✅ VERSIÓN CORREGIDA: Crea Checkout Session de Stripe con metadata
    Esto hará que las transacciones aparezcan en el dashboard de Stripe
    y el webhook recibirá el user_id correctamente.
    """
    try:
        # 1. Crear Checkout Session de Stripe (DIRECTO)
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'Recarga PITIUPI - ${amount:.2f} USD',
                        'description': f'User ID: {telegram_id}'
                    },
                    'unit_amount': int(amount * 100),  # Stripe usa centavos
                },
                'quantity': 1,
            }],
            mode='payment',
            
            # URLs importantes
            success_url=f'https://t.me/pitiupi_bot?payment=success&amount={amount}&user={telegram_id}',
            cancel_url=f'https://t.me/pitiupi_bot?payment=cancel',
            
            # ✅ METADATA CRÍTICA - ESTO FIJARÁ EL PROBLEMA
            metadata={
                'user_id': telegram_id,
                'telegram_id': telegram_id,
                'telegram_username': message.from_user.username or '',
                'amount_usd': f"{amount:.2f}",
                'source': 'pitiupi_bot'
            },
            
            # ✅ IDENTIFICACIÓN ALTERNATIVA (por si acaso)
            client_reference_id=telegram_id,
            
            # Opcional: Configuración adicional
            customer_creation='if_required',
        )
        
        logger.info(f"✅ Checkout Session creada: {session.id} para user {telegram_id}")
        
        # 2. Preparar mensaje para el usuario
        text = (
            "💳 <b>Pago con Stripe</b>\n\n"
            f"💰 Monto: <b>${amount:.2f} USD</b>\n"
            f"🆔 Tu ID: {telegram_id}\n\n"
            "Haz clic en el botón para completar el pago de forma segura."
        )
        
        # 3. Crear teclado con el enlace de Stripe
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Pagar con Tarjeta", url=session.url)],
            [InlineKeyboardButton(text="🔙 Cancelar", callback_data="menu:main")]
        ])
        
        # 4. Enviar mensaje
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
            
        return True
        
    except stripe.error.StripeError as e:
        logger.error(f"❌ Error de Stripe: {e}")
        # Fallback al método anterior
        return await fallback_to_old_method(message, telegram_id, amount)
    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}", exc_info=True)
        return await fallback_to_old_method(message, telegram_id, amount)

async def fallback_to_old_method(message: Message, telegram_id: str, amount: float):
    """Método de respaldo usando la redirección a página web"""
    try:
        separator = "&" if "?" in BASE_CHECKOUT_URL else "?"
        checkout_url = f"{BASE_CHECKOUT_URL}{separator}userId={telegram_id}&amount={amount}"
        
        text = (
            "🔧 <b>Usando método alternativo</b>\n\n"
            f"💰 Monto: <b>${amount:.2f} USD</b>\n"
            f"🆔 Tu ID: {telegram_id}\n\n"
            "Haz clic en el botón para ir a la página de pago."
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👉 Ir a Pagar", url=checkout_url)],
            [InlineKeyboardButton(text="🔙 Cancelar", callback_data="menu:main")]
        ])
        
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
        
        logger.warning(f"⚠️ Usando fallback para user {telegram_id}")
        return False
    except Exception as e:
        logger.error(f"❌ Error en fallback: {e}")
        await message.answer("❌ Error al crear el pago. Intenta más tarde.")
        return False

@deposit_router.callback_query(F.data == "deposit:cancel")
async def cancel_deposit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()