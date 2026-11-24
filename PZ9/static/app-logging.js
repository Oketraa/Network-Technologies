/* RoboTaxi integration with js-Logger 1.6.1 */
(function () {
  'use strict';
  if (window.TaxiLogger) return;
  if (!window.Logger || window.Logger.VERSION !== '1.6.1') {
    console.error('RoboTaxi: js-Logger 1.6.1 is not loaded.');
    return;
  }
  var Logger = window.Logger;
  Logger.useDefaults();
  Logger.setLevel(Logger.DEBUG);
  var consoleHandler = Logger.createDefaultHandler();
  var KEY = 'robotaxi.logs.v1', PREFIX = 'robotaxi.logs.v1:', LIMIT = 1000;
  var pages = new Set(['active.html', 'arrived.html', 'cancel.html', 'code_sent.html',
    'completed.html', 'contact.html', 'history.html', 'phone_code.html',
    'early_stop.html', 'index.html',
    'order.html', 'overview.html', 'profile.html', 'profile_edit.html', 'quote.html',
    'support.html', 'thankyou.html', 'ticket.html', 'trip.html', 'unlocked.html']);
  var levels = { debug: 10, info: 20, warn: 30, error: 40 }, threshold = 'debug';
  var entries = [], warnings = new Set(), sequence = 0;
  var instance = Date.now().toString(36) + Math.random().toString(36).slice(2);
  var isFile = location.protocol === 'file:';
  function screen(url) {
    try {
      var path = new URL(url, location.href).pathname.split('/').pop() || 'index.html';
      return pages.has(path) ? path : 'external';
    } catch (_) { return 'unknown'; }
  }
  var current = screen(location.href);
  var state = document.body.getAttribute('data-log-state');
  var descriptions = {
    'screen.view': 'Открыт экран', 'screen.restored': 'Экран восстановлен из истории',
    'navigation.link': 'Переход по ссылке', 'navigation.form': 'Отправлена форма',
    'form.changed': 'Изменено поле формы', 'validation.invalid': 'Поле формы заполнено некорректно',
    'auth.code_requested': 'Запрошен код входа', 'auth.code_submitted': 'Отправлен код входа',
    'auth.code_screen': 'Открыт экран ввода кода', 'auth.signout_requested': 'Выполнен выход',
    'order.quote_requested': 'Запрошен расчёт стоимости', 'order.quote_screen': 'Открыт расчёт стоимости',
    'order.confirmed': 'Подтверждён заказ', 'order.active_screen': 'Открыт активный заказ',
    'order.cancelled': 'Отменён заказ', 'order.cancelled_screen': 'Открыт экран отменённого заказа',
    'trip.arrival_opened': 'Открыты сведения о прибытии автомобиля',
    'trip.arrival_screen': 'Открыт экран прибытия автомобиля',
    'trip.unlock_requested': 'Запрошено открытие дверей', 'trip.unlocked_screen': 'Открыт экран посадки',
    'trip.start_requested': 'Запрошено начало поездки', 'trip.running_screen': 'Открыт экран поездки',
    'trip.finish_requested': 'Запрошено завершение поездки',
    'trip.early_stop_requested': 'Запрошена досрочная остановка',
    'trip.early_stop_confirmed': 'Подтверждена досрочная остановка',
    'trip.completed_screen': 'Открыт экран завершённой поездки',
    'trip.feedback_submitted': 'Отправлена оценка поездки', 'trip.feedback_screen': 'Открыт экран благодарности за отзыв',
    'profile.save_requested': 'Отправлены изменения профиля',
    'support.contact_opened': 'Открыта форма обращения в поддержку',
    'support.ticket_submitted': 'Отправлено обращение в поддержку', 'support.ticket_screen': 'Открыто обращение в поддержку',
    'javascript.error': 'Ошибка выполнения JavaScript',
    'javascript.unhandled_rejection': 'Необработанная ошибка Promise',
    'resource.load_failed': 'Не удалось загрузить ресурс',
    'logging.export_requested': 'Запрошено сохранение журнала в файл',
    'logging.export_failed': 'Не удалось подготовить файл журнала',
    'logging.persistence_degraded': 'Локальное хранение журнала ограничено',
    'logging.invalid_level': 'Указан неверный уровень логирования'
  };
  function cleanMessage(value) {
    return String(value).replace(/[\x00-\x1f\x7f]/g, ' ').slice(0, 500);
  }
  function formatRecord(record) {
    var date = new Date(record.time);
    function pad(n) { return String(n).padStart(2, '0'); }
    var stamp = pad(date.getDate()) + '.' + pad(date.getMonth() + 1) + '.' + date.getFullYear() +
      ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds());
    var message = record.message || descriptions[record.event] || record.event;
    if (record.context.target) message += ' → ' + record.context.target;
    if (record.context.errorType) message += ' (' + record.context.errorType + ')';
    return stamp + ' ' + record.level.toUpperCase().padEnd(5, ' ') + ' ' + message + ' [' + record.screen + ']';
  }
  function token(value) {
    return typeof value === 'string' && /^[a-zA-Z][a-zA-Z0-9_.-]{0,79}$/.test(value)
      ? value : 'unspecified';
  }
 
  function context(data) {
    var result = {};
    ['target', 'method', 'reason', 'errorType', 'tag'].forEach(function (key) {
      if (data && data[key] !== undefined) result[key] = token(data[key]);
    });
    return result;
  }
  function parse(raw, relay) {
    if (!raw) return [];
    var value = JSON.parse(relay ? raw.slice(PREFIX.length) : raw);
    if (!value || value.version !== 1 || !Array.isArray(value.entries)) throw new Error('format');
    return value.entries.filter(function (e) {
      return e && typeof e.id === 'string' && /^[a-z0-9-]{1,100}$/.test(e.id) &&
        typeof e.time === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(e.time) &&
        Object.hasOwn(levels, e.level) && pages.has(e.screen);
    }).slice(-LIMIT).map(function (e) {
      return { id: e.id, time: e.time, level: e.level, screen: e.screen,
        event: token(e.event), context: context(e.context),
        message: typeof e.message === 'string' ? cleanMessage(e.message) : undefined };
    });
  }
  function merge(other) {
    var byId = new Map();
    entries.concat(other).forEach(function (e) { byId.set(e.id, e); });
    entries = Array.from(byId.values()).sort(function (a, b) {
      return a.time.localeCompare(b.time);
    }).slice(-LIMIT);
  }
  try { merge(parse(localStorage.getItem(KEY), false)); }
  catch (_) { warnings.add('storage_read_unavailable'); }

  if (isFile && window.name.indexOf(PREFIX) === 0) {
    try { merge(parse(window.name, true)); } catch (_) { warnings.add('relay_invalid'); }
  }
  function persist() {
    try { merge(parse(localStorage.getItem(KEY), false)); }
    catch (_) { warnings.add('storage_read_unavailable'); }
    var raw = JSON.stringify({ version: 1, entries: entries });
    try { localStorage.setItem(KEY, raw); }
    catch (_) { warnings.add('storage_write_unavailable'); }
    if (isFile) {
      try {
        if (!window.name || window.name.indexOf(PREFIX) === 0) window.name = PREFIX + raw;
        else warnings.add('relay_name_occupied');
      } catch (_) { warnings.add('relay_write_unavailable'); }
    }
  }
  var reported = new Set();

  function log(level, event, data) {
    if (Object.hasOwn(levels, level)) Logger[level](token(event), context(data));
  }
  Logger.setHandler(function (messages, logContext) {
    var level = logContext.level.name.toLowerCase();
    if (!Object.hasOwn(levels, level)) return;
    var record = { id: instance + '-' + (++sequence), time: new Date().toISOString(),
      level: level, screen: current, event: token(messages[0]), context: context(messages[1]) };
  
    record.message = descriptions[record.event] || cleanMessage(messages[0]);
    entries.push(record);
    entries = entries.slice(-LIMIT);
    persist();
    if (levels[level] >= levels[threshold]) {
      try {
        consoleHandler([formatRecord(record)], logContext);
      } catch (_) { /* console optional */ }
    }
    warnings.forEach(function (reason) {
      if (!reported.has(reason)) {
        reported.add(reason);
        log('warn', 'logging.persistence_degraded', { reason: reason });
      }
    });
  });
  function exportLog() {
    var link, url;
    try {
      log('info', 'logging.export_requested');
      var text = entries.map(formatRecord).join('\r\n') + '\r\n';
      url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
      link = document.createElement('a');
      link.href = url;
      link.download = 'robotaxi-' + new Date().toISOString().replace(/[:.]/g, '-') + '.log';
      link.hidden = true;

      link.setAttribute('data-log-export', '');
      document.body.appendChild(link);
      link.click();
      return true;
    } catch (_) {
      log('error', 'logging.export_failed');
      return false;
    } finally {
      if (link) link.remove();
      if (url) setTimeout(function () { URL.revokeObjectURL(url); }, 10000);
    }
  }
  window.TaxiLogger = Object.freeze({
    debug: function (event, data) { return log('debug', event, data); },
    info: function (event, data) { return log('info', event, data); },
    warn: function (event, data) { return log('warn', event, data); },
    error: function (event, data) { return log('error', event, data); },
    export: exportLog,
    getLogs: function () { return JSON.parse(JSON.stringify(entries)); },
    setLevel: function (level) {
      if (Object.hasOwn(levels, level)) threshold = level;
      else log('warn', 'logging.invalid_level');
    }
  });
  function action(element) {
    var name = element.getAttribute('data-log-event');
    if (name) log(element.getAttribute('data-log-level') || 'info', name);
  }
  document.addEventListener('click', function (event) {
    if (event.defaultPrevented || !(event.target instanceof Element)) return;
    var link = event.target.closest('a[href]');
    if (!link || link.hasAttribute('data-log-export')) return;
    action(link);
    log('debug', 'navigation.link', { target: screen(link.href), method: 'GET' });
  });
  document.addEventListener('submit', function (event) {
    if (event.defaultPrevented) return;
    action(event.target);
    log('debug', 'navigation.form', { target: screen(event.target.dataset.logTarget || event.target.action),
      method: event.target.method.toUpperCase() });
  });
  document.addEventListener('invalid', function (event) {
    log('warn', 'validation.invalid', { tag: event.target.tagName.toLowerCase() });
  }, true);
  document.addEventListener('change', function (event) {
    if (event.target.matches('input, select, textarea'))
      log('debug', 'form.changed', { tag: event.target.tagName.toLowerCase() });
  });
  window.addEventListener('error', function (event) {
    if (event.target && event.target !== window) {
      log('error', 'resource.load_failed', { tag: event.target.tagName || 'unknown' });
    } else {
      log('error', 'javascript.error', { errorType: event.error && event.error.name || 'Error' });
    }
  }, true);
  window.addEventListener('unhandledrejection', function (event) {
    log('error', 'javascript.unhandled_rejection', {
      errorType: event.reason instanceof Error ? event.reason.name : 'UnknownRejection' });
  });
  document.addEventListener('keydown', function (event) {
    if ((event.ctrlKey || event.metaKey) && event.altKey && event.code === 'KeyL') {
      event.preventDefault();
      exportLog();
    }
  });
  window.addEventListener('pagehide', persist);
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) {
      if (isFile && window.name.indexOf(PREFIX) === 0) {
        try { merge(parse(window.name, true)); } catch (_) { /* keep memory journal */ }
      }
      log('debug', 'screen.restored');
    }
  });
  log('debug', 'screen.view');
  if (state) log('info', state);
}());
