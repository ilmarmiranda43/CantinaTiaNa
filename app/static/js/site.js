document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});

document.addEventListener("change", (event) => {
  if (event.target.id !== "responsavel-select") return;
  const phone = document.querySelector("#phone-input");
  if (phone) phone.disabled = Boolean(event.target.value);
});

document.getElementById('year').textContent = new Date().getFullYear();