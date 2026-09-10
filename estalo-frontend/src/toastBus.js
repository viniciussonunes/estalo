// Ponte pra código FORA de componentes React (hoje só api.js) conseguir
// mostrar um toast de erro sem virar hook nem receber props. ToastContext.jsx
// se registra aqui uma vez, no mount do <ToastProvider>; antes disso (ou se
// por algum motivo o Provider nunca montar), a função fica noop -- nunca
// quebra quem chama, só perde o aviso visual.
let mostrarToast = () => {};

export function registrarToastBus(fn) {
  mostrarToast = fn;
}

export function emitirToastErro(mensagem) {
  mostrarToast(mensagem, "erro");
}
