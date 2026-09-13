// Unified attachment dropzone: stacks selected files, previews them, and
// supports drag-and-drop. Initializes on every input[name="attachments"].
document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.querySelector('input[type="file"][name="attachments"]');
  const dropzone = document.getElementById('attachment-dropzone');
  const clearButton = document.getElementById('attachment-clear-button');
  const previewList = document.getElementById('attachment-preview-list');
  if (!fileInput || !dropzone || !previewList || !clearButton) {
    return;
  }

  let selectedFiles = [];

  const fileKey = (file) => [file.name, file.size, file.lastModified, file.type].join('::');

  const syncInputFiles = () => {
    const dataTransfer = new DataTransfer();
    selectedFiles.forEach((file) => dataTransfer.items.add(file));
    fileInput.files = dataTransfer.files;
  };

  const mergeFiles = (incomingFiles) => {
    const known = new Set(selectedFiles.map(fileKey));
    Array.from(incomingFiles || []).forEach((file) => {
      const key = fileKey(file);
      if (!known.has(key)) {
        selectedFiles.push(file);
        known.add(key);
      }
    });
  };

  const updatePreview = () => {
    if (!selectedFiles.length) {
      previewList.innerHTML = '';
      return;
    }

    previewList.innerHTML = '<ul>' + selectedFiles.map((file) => {
      const isImage = file.type.startsWith('image/');
      const isVideo = file.type.startsWith('video/');
      const safeName = file.name || 'Selected file';
      let label = 'Document';
      if (isImage) {
        label = 'Image';
      } else if (isVideo) {
        label = 'Video';
      }
      return `<li>${safeName} (${label})</li>`;
    }).join('') + '</ul>';
  };

  fileInput.addEventListener('change', () => {
    mergeFiles(fileInput.files);
    syncInputFiles();
    updatePreview();
  });

  clearButton.addEventListener('click', () => {
    selectedFiles = [];
    syncInputFiles();
    updatePreview();
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
    const droppedFiles = event.dataTransfer?.files || [];
    if (droppedFiles.length) {
      mergeFiles(droppedFiles);
      syncInputFiles();
      updatePreview();
    }
  });

  selectedFiles = Array.from(fileInput.files || []);
  updatePreview();
});
