(function(){
  // Gallery
  function initGallery(root){
    if(!root) return;
    const images = JSON.parse(root.dataset.images || '[]');
    const main = root.querySelector('#agGalleryMain');
    const thumbs = Array.from(root.querySelectorAll('.ag-thumb'));
    const prev = root.querySelector('.ag-gallery__nav.--prev');
    const next = root.querySelector('.ag-gallery__nav.--next');
    let idx = 0;

    function show(i){
      if(!images.length) return;
      idx = (i+images.length)%images.length;
      main.src = images[idx];
      thumbs.forEach((t,k)=>t.classList.toggle('is-active', k===idx));
    }
    thumbs.forEach((t,k)=>t.addEventListener('click', ()=>show(k)));
    prev && prev.addEventListener('click', ()=>show(idx-1));
    next && next.addEventListener('click', ()=>show(idx+1));

    // swipe
    let sx=0; root.addEventListener('touchstart',e=>sx=e.touches[0].clientX,{passive:true});
    root.addEventListener('touchend',e=>{
      const dx=e.changedTouches[0].clientX-sx;
      if(Math.abs(dx)>40) dx>0?show(idx-1):show(idx+1);
    });
  }

  document.addEventListener('DOMContentLoaded', ()=>{
    initGallery(document.getElementById('agGallery'));

    // Progressive “Load more” spinner toggle (if present)
    const loadMore = document.getElementById('loadMoreButton');
    if(loadMore){
      loadMore.addEventListener('click', function(){
        const spinner = this.querySelector('.spinner-border');
        const text = this.querySelector('.button-text');
        spinner && spinner.classList.remove('d-none');
        text && text.classList.add('d-none');
      });
    }
  });
})();