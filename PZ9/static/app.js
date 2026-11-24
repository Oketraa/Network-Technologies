/* Small enhancements over native form submissions. */
document.addEventListener('click', (event) => {
  const closeNotice = event.target.closest('[data-dismiss-notice]');
  if (closeNotice) closeNotice.closest('.notice-layer').remove();

  const dialogTrigger = event.target.closest('[data-open-dialog]');
  if (dialogTrigger) document.getElementById(dialogTrigger.dataset.openDialog).showModal();

  if (event.target.closest('[data-export-journal]')) {
    const status = document.querySelector('[data-export-status]');
    status.textContent = window.TaxiLogger?.export()
      ? 'Журнал подготовлен.'
      : 'Не удалось сохранить журнал.';
  }
});
