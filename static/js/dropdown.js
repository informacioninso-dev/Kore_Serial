// static/js/dropdown.js - Funcionalidad de dropdowns reutilizable

/**
 * Toggle dropdown menu
 * @param {Event} event - Click event
 */
function toggleDropdown(event) {
  event.stopPropagation();
  const button = event.currentTarget;
  const dropdown = button.nextElementSibling;

  if (!dropdown || !dropdown.classList.contains('dropdown-menu')) {
    console.warn('Dropdown menu not found');
    return;
  }

  const wasShown = dropdown.classList.contains('show');

  // Cerrar todos los dropdowns abiertos
  closeAllDropdowns();

  // Toggle el dropdown actual
  if (!wasShown) {
    dropdown.classList.add('show');

    // Ajustar posición si se sale del viewport
    adjustDropdownPosition(dropdown);
  }
}

/**
 * Cierra todos los dropdowns abiertos
 */
function closeAllDropdowns() {
  document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
    menu.classList.remove('show');
  });
}

/**
 * Ajusta la posición del dropdown si se sale del viewport
 * @param {HTMLElement} dropdown - Elemento del dropdown
 */
function adjustDropdownPosition(dropdown) {
  const rect = dropdown.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  // Si se sale por la derecha, alinear a la izquierda
  if (rect.right > viewportWidth) {
    dropdown.style.right = '0';
    dropdown.style.left = 'auto';
  }

  // Si se sale por abajo, mostrar hacia arriba
  if (rect.bottom > viewportHeight) {
    dropdown.style.bottom = '100%';
    dropdown.style.top = 'auto';
    dropdown.style.marginTop = '0';
    dropdown.style.marginBottom = '0.25rem';
  }
}

// Event listeners globales
document.addEventListener('DOMContentLoaded', function() {
  // Cerrar dropdown al hacer click fuera
  document.addEventListener('click', function(event) {
    if (!event.target.closest('.dropdown-menu') &&
        !event.target.closest('button[onclick*="toggleDropdown"]')) {
      closeAllDropdowns();
    }
  });

  // Cerrar dropdown al presionar ESC
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
      closeAllDropdowns();
    }
  });

  // Cerrar dropdowns al hacer scroll (opcional)
  let scrollTimeout;
  window.addEventListener('scroll', function() {
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(function() {
      closeAllDropdowns();
    }, 100);
  }, { passive: true });
});
