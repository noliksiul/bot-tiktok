# imghdr.py - parche temporal para Python 3.13
# Este archivo reemplaza el módulo estándar eliminado en Python 3.13
# Solo se incluye lo mínimo para que python-telegram-bot no falle.

def what(file, h=None):
    # No hace detección real de imágenes, pero evita el error de importación
    return None