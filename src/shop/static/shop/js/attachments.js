// Unified attachment dropzone with fast parallel AJAX staging uploads.
//
// Files are validated client-side, photos are downscaled/compressed, then
// each file is uploaded immediately to the staging endpoint (with progress
// bars, a couple of uploads at a time) instead of riding inside the giant
// form POST. The form submits only the staged attachment IDs via a hidden
// `staged_attachments` input. Without JavaScript the classic multipart path
// still works because the file input is only emptied once JS takes over.
document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.querySelector('input[type="file"][name="attachments"]');
  const previewList = document.getElementById('attachment-preview-list');
  const clearButton = document.getElementById('attachment-clear-button');
  const section = document.querySelector('[data-testid="attachment-upload-section"]');
  if (!fileInput || !previewList || !clearButton || !section) {
    return;
  }
  const form = section.closest('form') || fileInput.closest('form');
  const dropzone = document.getElementById('attachment-dropzone') || section;
  const uploadUrl = section.dataset.uploadUrl;
  const deleteUrlBase = section.dataset.deleteUrl;
  if (!form || !uploadUrl || !deleteUrlBase) {
    return;
  }

  const MAX_UPLOAD_BYTES = 500 * 1024 * 1024; // keep in sync with shop.forms.base
  const MAX_FILES = 10; // keep in sync with shop.forms.base
  const MAX_CONCURRENT_UPLOADS = 2;
  const IMAGE_MAX_DIMENSION = 2560;
  const IMAGE_COMPRESS_MIN_BYTES = 1.5 * 1024 * 1024;
  const ALLOWED_EXTENSIONS = new Set([
    '.jpg', '.jpeg', '.png', '.gif', '.webp',
    '.mp4', '.webm', '.mov',
    '.pdf', '.doc', '.docx',
  ]);
  const ALLOWED_CONTENT_TYPES = /^image\/(jpeg|png|gif|webp)|video\/(mp4|webm|quicktime)|application\/(pdf|msword|vnd\.openxmlformats-officedocument\.wordprocessingml\.document)$/;

  const csrfToken = (form.querySelector('input[name="csrfmiddlewaretoken"]') || {}).value || '';
  const hiddenInput = form.querySelector('input[name="staged_attachments"]');
  const submitButtons = Array.from(form.querySelectorAll('button[type="submit"]'));

  let items = []; // {key, file, status, error, stagedId, xhr}
  let waitingForSubmit = false;

  const fileKey = (file) => [file.name, file.size, file.lastModified, file.type].join('::');

  const formatBytes = (bytes) => {
    if (bytes >= 1024 * 1024) {
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }
    return Math.max(1, Math.round(bytes / 1024)) + ' KB';
  };

  const labelFor = (file) => {
    if (file.type.startsWith('image/')) return 'Image';
    if (file.type.startsWith('video/')) return 'Video';
    return 'Document';
  };

  const validateFile = (file) => {
    if (file.size > MAX_UPLOAD_BYTES) {
      return 'Uploaded attachments must be no larger than ' + Math.floor(MAX_UPLOAD_BYTES / (1024 * 1024)) + ' MB.';
    }
    const extension = (file.name.split('.').pop() || '').toLowerCase();
    if (!ALLOWED_EXTENSIONS.has('.' + extension)) {
      return 'Unsupported attachment file type.';
    }
    if (file.type && !ALLOWED_CONTENT_TYPES.test(file.type)) {
      return 'Unsupported attachment file type.';
    }
    return null;
  };

  const maybeCompressImage = (file) => new Promise((resolve) => {
    if (!file.type.startsWith('image/') || file.size < IMAGE_COMPRESS_MIN_BYTES || typeof createImageBitmap !== 'function') {
      resolve(file);
      return;
    }
    createImageBitmap(file).then((bitmap) => {
      const scale = Math.min(1, IMAGE_MAX_DIMENSION / Math.max(bitmap.width, bitmap.height));
      if (scale >= 1 && file.size < 4 * 1024 * 1024) {
        resolve(file);
        return;
      }
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext('2d');
      if (!context) {
        resolve(file);
        return;
      }
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        if (blob && blob.size < file.size) {
          resolve(new File([blob], file.name.replace(/\.(png|jpe?g|webp)$/i, '.jpg'), {
            type: 'image/jpeg',
            lastModified: Date.now(),
          }));
        } else {
          resolve(file);
        }
      }, 'image/jpeg', 0.85);
    }).catch(() => resolve(file));
  });

  const deleteStaged = (stagedId) => {
    if (!stagedId) {
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open('POST', deleteUrlBase.replace('/0/', '/' + stagedId + '/'));
    if (csrfToken) {
      xhr.setRequestHeader('X-CSRFToken', csrfToken);
    }
    xhr.send();
  };

  const removeItem = (item) => {
    items = items.filter((candidate) => candidate !== item);
    if (item.xhr && item.status === 'uploading') {
      item.xhr.abort();
    }
    deleteStaged(item.stagedId);
    render();
    pump();
  };

  const startUpload = (item) => {
    item.status = 'uploading';
    item.xhr = null;
    render();
    const xhr = new XMLHttpRequest();
    item.xhr = xhr;
    xhr.open('POST', uploadUrl);
    if (csrfToken) {
      xhr.setRequestHeader('X-CSRFToken', csrfToken);
    }
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable) {
        return;
      }
      const row = previewList.querySelector('li[data-key="' + CSS.escape(item.key) + '"] progress');
      if (row) {
        row.value = Math.round((event.loaded / event.total) * 100);
      }
    });
    xhr.addEventListener('load', () => {
      if (xhr.status === 201) {
        try {
          item.stagedId = JSON.parse(xhr.responseText).id;
          item.status = 'done';
        } catch {
          item.status = 'failed';
          item.error = 'Unexpected server response.';
        }
      } else {
        item.status = 'failed';
        try {
          item.error = JSON.parse(xhr.responseText).error || 'Upload failed.';
        } catch {
          item.error = 'Upload failed.';
        }
      }
      render();
      pump();
    });
    xhr.addEventListener('error', () => {
      item.status = 'failed';
      item.error = 'Upload failed. Check your connection and retry.';
      render();
      pump();
    });
    xhr.addEventListener('abort', () => {
      item.status = 'failed';
      item.error = 'Upload cancelled.';
      render();
      pump();
    });
    const payload = new FormData();
    payload.append('file', item.file, item.file.name);
    xhr.send(payload);
  };

  const enqueue = (item) => {
    item.status = 'queued';
    item.error = null;
    render();
    pump();
  };

  const pump = () => {
    const active = items.filter((item) => item.status === 'uploading').length;
    const capacity = Math.max(0, MAX_CONCURRENT_UPLOADS - active);
    items.filter((item) => item.status === 'queued').slice(0, capacity).forEach(startUpload);
    maybeFinalizeSubmit();
  };

  const busyCount = () => items.filter((item) => item.status === 'compressing' || item.status === 'queued' || item.status === 'uploading').length;
  const failedCount = () => items.filter((item) => item.status === 'failed' || item.status === 'rejected').length;

  const updateHiddenInput = () => {
    if (!hiddenInput) {
      return;
    }
    hiddenInput.value = items
      .filter((item) => item.stagedId)
      .map((item) => item.stagedId)
      .join(',');
  };

  const clearInputFiles = () => {
    fileInput.files = new DataTransfer().files;
  };

  const maybeFinalizeSubmit = () => {
    if (!waitingForSubmit || busyCount() > 0) {
      return;
    }
    waitingForSubmit = false;
    submitButtons.forEach((button) => { button.disabled = false; });
    if (failedCount() === 0) {
      updateHiddenInput();
      form.submit();
    }
  };

  form.addEventListener('submit', (event) => {
    updateHiddenInput();
    if (failedCount() > 0) {
      event.preventDefault();
      render();
      return;
    }
    if (busyCount() > 0) {
      event.preventDefault();
      waitingForSubmit = true;
      submitButtons.forEach((button) => { button.disabled = true; });
      render();
    }
  });

  const buildRow = (item) => {
    const row = document.createElement('li');
    row.className = 'attachment-item';
    row.dataset.key = item.key;
    row.dataset.status = item.status;

    const nameSpan = document.createElement('span');
    nameSpan.className = 'attachment-item-name';
    nameSpan.textContent = item.file.name;
    row.appendChild(nameSpan);

    const kindTag = document.createElement('span');
    kindTag.className = 'tag is-light ml-2';
    kindTag.textContent = labelFor(item.file);
    row.appendChild(kindTag);

    const sizeSpan = document.createElement('span');
    sizeSpan.className = 'has-text-grey is-size-7 ml-2';
    sizeSpan.textContent = formatBytes(item.file.size);
    row.appendChild(sizeSpan);

    if (item.status === 'queued' || item.status === 'compressing') {
      const tag = document.createElement('span');
      tag.className = 'tag is-info is-light ml-2';
      tag.textContent = 'Waiting';
      row.appendChild(tag);
    } else if (item.status === 'uploading') {
      const bar = document.createElement('progress');
      bar.className = 'progress is-small is-primary ml-2 attachment-progress';
      bar.max = 100;
      bar.value = 0;
      row.appendChild(bar);
    } else if (item.status === 'done') {
      const tag = document.createElement('span');
      tag.className = 'tag is-success ml-2';
      tag.textContent = 'Uploaded';
      row.appendChild(tag);
    } else if (item.status === 'failed' || item.status === 'rejected') {
      const tag = document.createElement('span');
      tag.className = 'tag is-danger ml-2';
      tag.textContent = item.error || 'Failed';
      row.appendChild(tag);
      if (item.status === 'failed') {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.className = 'button is-small is-warning ml-2';
        retry.textContent = 'Retry';
        retry.addEventListener('click', () => enqueue(item));
        row.appendChild(retry);
      }
      const help = document.createElement('p');
      help.className = 'help is-danger mb-0 ml-2';
      help.textContent = item.error || 'Failed';
      row.appendChild(help);
    }

    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'delete ml-2';
    removeButton.setAttribute('aria-label', 'Remove ' + item.file.name);
    removeButton.addEventListener('click', () => removeItem(item));
    row.appendChild(removeButton);
    return row;
  };

  const render = () => {
    previewList.textContent = '';
    updateHiddenInput();
    if (!items.length) {
      return;
    }
    const list = document.createElement('ul');
    items.forEach((item) => list.appendChild(buildRow(item)));
    previewList.appendChild(list);
  };

  const acceptFiles = (incomingFiles) => {
    const known = new Set(items.map((item) => item.key));
    Array.from(incomingFiles || []).forEach((file) => {
      const key = fileKey(file);
      if (known.has(key)) {
        return;
      }
      const activeFiles = items.filter((item) => item.status !== 'rejected').length;
      if (activeFiles >= MAX_FILES) {
        items.push({
          key, file, status: 'rejected', error: 'No more than ' + MAX_FILES +
            ' attachments may be uploaded at once.', stagedId: null, xhr: null,
        });
        known.add(key);
        return;
      }
      const error = validateFile(file);
      const item = {
        key, file, status: error ? 'rejected' : 'compressing', error,
        stagedId: null, xhr: null,
      };
      items.push(item);
      known.add(key);
      if (!error) {
        maybeCompressImage(file).then((uploadFile) => {
          if (item.status === 'compressing') {
            item.file = uploadFile;
            enqueue(item);
          }
        });
      }
    });
    clearInputFiles();
    render();
    pump();
  };

  clearButton.addEventListener('click', () => {
    items.slice().forEach(removeItem);
    waitingForSubmit = false;
    submitButtons.forEach((button) => { button.disabled = false; });
    render();
  });

  ['dragenter', 'dragover'].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add('is-active');
    });
  });
  ['dragleave', 'drop'].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove('is-active');
    });
  });

  dropzone.addEventListener('drop', (event) => {
    const droppedFiles = event.dataTransfer && event.dataTransfer.files;
    if (droppedFiles && droppedFiles.length) {
      acceptFiles(droppedFiles);
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files && fileInput.files.length) {
      acceptFiles(fileInput.files);
    }
  });

  clearInputFiles();
  updateHiddenInput();
});
