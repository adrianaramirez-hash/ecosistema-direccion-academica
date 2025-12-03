st.subheader("Panel inicial")

st.write(f"Vista actual: **{vista}**")
if carrera:
    st.write(f"Carrera seleccionada: **{carrera}**")
else:
    st.write("Carrera seleccionada: *no aplica para esta vista*")

st.write(f"Apartado seleccionado: **{seccion}**")

st.markdown("---")

if seccion == "Observación de clases":
    # Llamamos al módulo de reportes
    observacion_clases.render_observacion_clases(vista, carrera)
else:
    st.info("Este apartado aún está en construcción dentro del ecosistema.")
