 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/procesar_encuestas_calidad.py b/procesar_encuestas_calidad.py
new file mode 100644
index 0000000000000000000000000000000000000000..d2ad27ebafc324b11a5ca0a36691411f441668e4
--- /dev/null
+++ b/procesar_encuestas_calidad.py
@@ -0,0 +1,13 @@
+"""
+Módulo de compatibilidad para el botón de procesamiento ORIGINAL → PROCESADO.
+
+El procesamiento real no está disponible en este repositorio. Implementa la
+lógica correspondiente y reemplaza la excepción para habilitarlo.
+"""
+
+
+def main(_service_account_json: str):
+    raise NotImplementedError(
+        "El procesamiento ORIGINAL → PROCESADO no está implementado en este entorno. "
+        "Sustituye `procesar_encuestas_calidad.main` con tu lógica de conversión."
+    )
 
EOF
)
