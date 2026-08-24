# ============================================================================
# core/utils/__init__.py
# ============================================================================

from decimal import Decimal
from django.core.exceptions import ValidationError

class UnitConverter:
    """
    Utilidad para convertir cantidades entre unidades.
    CRÍTICO para ISO 13485: Conversión precisa de unidades.
    """
    
    @staticmethod
    def convert_to_base_unit(quantity, from_unit, product):
        """
        Convierte cantidad de cualquier unidad a unidad base del producto.
        
        Ejemplo:
            Producto base_unit = kg (factor_to_base = 1)
            from_unit = g (factor_to_base = 0.001)
            quantity = 500
            resultado = 500 * 0.001 = 0.5 kg
        """
        if not quantity:
            return Decimal('0')
        
        quantity = Decimal(str(quantity))
        
        # Si ya está en unidad base, retornar directo
        if from_unit.id == product.base_unit.id:
            return quantity
        
        # Validar categorías compatibles
        if from_unit.category != product.base_unit.category:
            raise ValidationError(
                f"ERROR: No se puede convertir {from_unit.name} ({from_unit.category}) "
                f"a {product.base_unit.name} ({product.base_unit.category}). "
                f"Las categorías deben coincidir."
            )
        
        # Validar factor válido
        if from_unit.factor_to_base <= 0:
            raise ValidationError(
                f"ERROR: El factor de conversión de {from_unit.name} es inválido: "
                f"{from_unit.factor_to_base}"
            )
        
        # Convertir: cantidad * factor_to_base
        converted = quantity * from_unit.factor_to_base
        
        return converted.quantize(Decimal('0.0001'))  # 4 decimales
    
    @staticmethod
    def convert_from_base_unit(quantity_in_base, to_unit, product):
        """
        Convierte de unidad base a otra unidad (para UI).
        """
        if not quantity_in_base:
            return Decimal('0')
        
        quantity_in_base = Decimal(str(quantity_in_base))
        
        if to_unit.id == product.base_unit.id:
            return quantity_in_base
        
        if to_unit.category != product.base_unit.category:
            raise ValidationError(
                f"No se puede convertir de {product.base_unit.name} a {to_unit.name}"
            )
        
        if to_unit.factor_to_base <= 0:
            raise ValidationError(f"Factor inválido para {to_unit.name}")
        
        converted = quantity_in_base / to_unit.factor_to_base
        
        return converted.quantize(Decimal('0.0001'))