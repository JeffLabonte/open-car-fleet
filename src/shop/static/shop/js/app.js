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
      const prefix = linkPath.endsWith('/') ? linkPath : `${linkPath}/`;
      const isCurrent = linkPath === '/' || linkPath === ''
        ? path === '/' || path.startsWith('/fleets/')
        : path === linkPath || path === prefix || path.startsWith(prefix);
      if (isCurrent) {
        link.setAttribute('aria-current', 'page');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  };

  const initAccountMenu = () => {
    document.querySelectorAll('details[data-menu]').forEach((menu) => {
      const summary = menu.querySelector('summary');
      let lastFocus = null;
      menu.addEventListener('toggle', () => {
        if (menu.open) {
          lastFocus = document.activeElement;
        } else if (lastFocus && menu.contains(lastFocus)) {
          if (summary) summary.focus();
          lastFocus = null;
        }
      });
      document.addEventListener('click', (event) => {
        if (!menu.contains(event.target)) {
          menu.removeAttribute('open');
        }
      });
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && menu.open) {
          const hadFocusInside = menu.contains(document.activeElement);
          menu.removeAttribute('open');
          if (hadFocusInside && summary) {
            summary.focus();
          }
        }
      });
      menu.querySelectorAll('a, button').forEach((item) => {
        item.addEventListener('click', () => menu.removeAttribute('open'));
      });
    });
  };

  const openErrorDialogs = () => {
    document.querySelectorAll('dialog[data-open-on-error="true"]').forEach((dialog) => {
      if (dialog instanceof HTMLDialogElement && typeof dialog.showModal === 'function') {
        dialog.showModal();
      }
    });
  };

  const collapseLargeTitle = () => {
    const title = document.querySelector('.page-title');
    if (!title) return;
    const threshold = 40;
    const onScroll = () => {
      if (window.scrollY > threshold) {
        title.classList.add('is-collapsed');
      } else {
        title.classList.remove('is-collapsed');
      }
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  };

  const initUnsavedChangesWarning = () => {
    const forms = document.querySelectorAll('form[data-warn-unsaved="true"]');
    forms.forEach((form) => {
      let dirty = false;
      form.addEventListener('input', () => { dirty = true; });
      form.addEventListener('change', () => { dirty = true; });
      form.addEventListener('submit', () => { dirty = false; });
      window.addEventListener('beforeunload', (event) => {
        if (dirty) {
          event.preventDefault();
          event.returnValue = '';
        }
      });
    });
  };

  const initFlashMessages = () => {
    document.querySelectorAll('[data-testid="flash-message"]').forEach((message) => {
      const tags = message.dataset.messageTags || '';
      const isPersistent = tags === 'error' || tags === 'warning';
      const dismiss = () => {
        message.style.transition = 'opacity 0.2s ease';
        message.style.opacity = '0';
        window.setTimeout(() => message.remove(), 200);
      };
      const closeButton = message.querySelector('[data-dismiss-flash]');
      if (closeButton) {
        closeButton.addEventListener('click', dismiss);
      }
      if (!isPersistent) {
        let timer = window.setTimeout(dismiss, 5000);
        message.addEventListener('mouseenter', () => window.clearTimeout(timer));
        message.addEventListener('focusin', () => window.clearTimeout(timer));
      }
    });
  };

  const expandDetailsFromHash = () => {
    const expandTarget = () => {
      const encodedId = window.location.hash.slice(1);
      if (!encodedId) return;
      let id;
      try {
        id = decodeURIComponent(encodedId);
      } catch {
        return;
      }
      const target = document.getElementById(id);
      if (!(target instanceof HTMLDetailsElement) || !target.matches('[data-expand-on-hash]')) {
        return;
      }
      target.open = true;
      window.requestAnimationFrame(() => target.scrollIntoView({ block: 'start' }));
    };

    window.addEventListener('hashchange', expandTarget);
    expandTarget();
  };

  initDialogs();
  markCurrentNav();
  initAccountMenu();
  expandDetailsFromHash();
  openErrorDialogs();
  collapseLargeTitle();
  initFlashMessages();
  initUnsavedChangesWarning();
})();
