// Blog post editor preview functionality
document.addEventListener('DOMContentLoaded', function() {
    // Setup preview buttons
    const previewButtons = document.querySelectorAll('.preview-btn');
    
    previewButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Get the language code from the button's data attribute
            const langCode = this.dataset.lang;
            
            // Get the content from the appropriate fields
            const title = document.getElementById(`title_${langCode}`).value;
            const excerpt = document.getElementById(`excerpt_${langCode}`).value;
            const content = document.getElementById(`content_${langCode}`).value;
            
            // Create a modal for preview
            const modal = document.createElement('div');
            modal.className = 'modal fade preview-modal';
            modal.id = `previewModal_${langCode}`;
            modal.setAttribute('tabindex', '-1');
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-labelledby', 'previewModalLabel');
            
            modal.innerHTML = `
                <div class="modal-dialog modal-xl" role="document">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="previewModalLabel">Preview (${langCode.toUpperCase()})</h5>
                            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                <span aria-hidden="true">&times;</span>
                            </button>
                        </div>
                        <div class="modal-body">
                            <div class="preview-container p-3">
                                <h1>${title || 'No Title'}</h1>
                                ${excerpt ? `<div class="excerpt lead mb-4">${excerpt}</div>` : ''}
                                <hr class="my-4">
                                <div class="content">${content || 'No Content'}</div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
                        </div>
                    </div>
                </div>
            `;
            
            // Add to document and show
            document.body.appendChild(modal);
            $(`#previewModal_${langCode}`).modal('show');
            
            // Remove from DOM when hidden
            $(`#previewModal_${langCode}`).on('hidden.bs.modal', function() {
                $(this).remove();
            });
        });
    });
});