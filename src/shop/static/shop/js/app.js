(() => {
  const initDialogs = () => {
    document.querySelectorAll('[data-dialog-open]').forEach((trigger) => {
      trigger.addEventListener('click', () => {
        const target = document.getElementById(trigger.dataset.dialogOpen);
        if (!(target instanceof HTMLDialogElement)) {
          return;
        }
        const actionForm = target.querySelector('[data-dialog-action-form]');
        if (actionForm && trigger.dataset.dialogAction) {
          actionForm.setAttribute('action', trigger.dataset.dialogAction);
        }
        target.showModal();
      });
    });

    document.querySelectorAll('[data-dialog-close]').forEach((trigger) => {
      trigger.addEventListener('click', () => {
        trigger.closest('dialog')?.close();
      });
    });

    document.querySelectorAll('dialog.dialog').forEach((dialog) => {
      dialog.addEventListener('click', (event) => {
        if (event.target === dialog) {
          dialog.close();
        }
      });
    });
  };

  const markCurrentNav = () => {
    const path = window.location.pathname;
    document.querySelectorAll('.app-navlink, .app-tab').forEach((link) => {
      const linkPath = new URL(link.href, window.location.origin).pathname;
      let isCurrent = false;
      if (linkPath === '/' || linkPath === '') {
        isCurrent = path === '/' || path.startsWith('/garages/');
      } else {
        const prefix = linkPath.endsWith('/') ? linkPath : `${linkPath}/`;
        isCurrent = path === linkPath || path === prefix || path.startsWith(prefix);
      }
      if (isCurrent) {
        link.setAttribute('aria-current', 'page');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  };

  const initAccountMenu = () => {
    document.querySelectorAll('details[data-menu]').forEach((menu) => {
      document.addEventListener('click', (event) => {
        if (!menu.contains(event.target)) {
          menu.removeAttribute('open');
        }
      });
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          menu.removeAttribute('open');
        }
      });
      menu.querySelectorAll('a, button').forEach((item) => {
        item.addEventListener('click', () => menu.removeAttribute('open'));
      });
    });
  };

  initDialogs();
  markCurrentNav();
  initAccountMenu();
})();
