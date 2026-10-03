/* Formato de importes en español. */
const euros = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });

export const formatearEuros = (importe) => euros.format(importe);
