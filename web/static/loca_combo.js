/* 페이지 안의 내부 링크에 현재 입력을 이어붙인다.

   거주지·근무지는 2페이지에서 한 번 받고 3~6페이지가 계속 쓴다. 그런데 상단
   네비게이션과 일부 버튼은 템플릿·JSON에 링크가 박혀 있어서, 서버에서 고치려면
   그 파일들을 모두 손대야 하고 하나만 놓쳐도 파라미터가 사라진다.
   여기서 한 번에 이어붙이면 링크가 어디에 정의돼 있든 유지된다.

   이미 ?가 붙은 링크는 그 값을 우선하고 빠진 것만 채운다(예: ?dong=청림동). */
(function () {
  var current = new URLSearchParams(window.location.search);
  if (!current.toString()) { return; }

  var KEYS = ['residence', 'workplace', 'deposit', 'rent', 'work_days',
              'depart_time', 'age'];
  var carry = new URLSearchParams();
  KEYS.forEach(function (k) {
    var v = current.get(k);
    if (v) { carry.set(k, v); }
  });
  if (!carry.toString()) { return; }

  document.querySelectorAll('a[href]').forEach(function (a) {
    var href = a.getAttribute('href');
    if (!href || href.charAt(0) !== '/' || href.indexOf('//') === 0) { return; }

    var parts = href.split('?');
    var params = new URLSearchParams(parts[1] || '');
    carry.forEach(function (v, k) {
      if (!params.has(k)) { params.set(k, v); }
    });
    a.setAttribute('href', parts[0] + '?' + params.toString());
  });

  // GET 폼도 마찬가지다. action 의 쿼리스트링은 브라우저가 버리므로
  // hidden 으로 실어야 다음 페이지까지 간다.
  document.querySelectorAll('form[method="get"], form:not([method])').forEach(function (form) {
    carry.forEach(function (v, k) {
      if (form.querySelector('[name="' + k + '"]')) { return; }
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = k;
      input.value = v;
      form.appendChild(input);
    });
  });
})();

/* 거주지·근무지·후보지 입력 자동완성.

   자유 입력이 기본이고 자동완성은 보조다. resolve_place 가 역명·도로명·지번을
   모두 처리하므로, 목록에 없는 값을 직접 쳐도 통해야 한다.

   행정동 427개를 미리 내려받으면 첫 로딩이 무거워지므로 두 글자부터 서버에
   물어본다. 요청이 실패해도 입력창은 그대로 쓸 수 있다.

   범위 좁히기 - 경로는 거주동별 누적 80% 목적지만 수집해서 모든 조합이 있지
   않다(거주동당 평균 72곳). 전체를 열어두면 사용자가 없는 조합을 고르고
   결과 화면에서야 실패를 알게 되므로, 갈 수 있는 곳만 제안한다.
     data-place="workplace" -> 입력된 거주지에서 갈 수 있는 근무지
     data-place="area"      -> 입력된 근무지로 갈 수 있는 거주지

   마크업:
     <div class="combo" data-combo>
       <input data-place="residence|workplace|area" ...>
       <ul class="combo-list" role="listbox" hidden></ul>
     </div>
*/
(function () {
  function val(selector) {
    var el = document.querySelector(selector);
    return el ? el.value.trim() : '';
  }

  function buildUrl(input, q) {
    var url = '/api/suggest?q=' + encodeURIComponent(q);
    var kind = input.dataset.place;

    if (kind === 'workplace') {
      var home = val('input[data-place="residence"]');
      if (home) { url += '&kind=work&home=' + encodeURIComponent(home); }
    } else if (kind === 'area') {
      // 4·5페이지는 근무지가 hidden 으로 실려 온다
      var work = val('input[name="workplace"]');
      if (work) { url += '&kind=home&work=' + encodeURIComponent(work); }
    }
    return url;
  }

  function setup(box) {
    var input = box.querySelector('input');
    var list = box.querySelector('.combo-list');
    if (!input || !list) { return; }

    var timer = null, items = [], cursor = -1, lastQuery = '';
    var hintEl = box.parentNode.querySelector('.combo-hint')
              || box.parentNode.querySelector('.field-hint');
    var baseHint = hintEl ? hintEl.textContent : '';

    function close() {
      list.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      cursor = -1;
    }

    function paint() {
      Array.prototype.forEach.call(list.children, function (li, i) {
        li.setAttribute('aria-selected', i === cursor ? 'true' : 'false');
      });
    }

    function choose(i) {
      if (!items[i]) { return; }
      input.value = items[i].value;
      lastQuery = items[i].value;
      close();
    }

    function render(data) {
      list.innerHTML = '';
      items = (data && data.items) || [];
      var scoped = !!(data && data.scoped);

      if (hintEl) {
        hintEl.textContent = scoped
          ? '입력하신 조건으로 오갈 수 있는 지역만 보여드려요.'
          : baseHint;
      }

      if (!items.length) {
        var empty = document.createElement('li');
        empty.className = 'empty';
        empty.textContent = scoped
          ? '이 조건으로 오갈 수 있는 지역 중에는 없어요.'
          : '검색 결과가 없어요. 역명이나 주소로 입력해보세요.';
        list.appendChild(empty);
      } else {
        items.forEach(function (item, i) {
          var li = document.createElement('li');
          li.setAttribute('role', 'option');
          var gu = document.createElement('span');
          gu.className = 'gu';
          gu.textContent = (item.label || '').split(' ')[0];
          var dong = document.createElement('span');
          dong.className = 'dong';
          dong.textContent = item.value;
          li.appendChild(gu);
          li.appendChild(dong);
          li.addEventListener('mousedown', function (e) {
            e.preventDefault();
            choose(i);
          });
          list.appendChild(li);
        });
      }
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      cursor = -1;
    }

    input.setAttribute('autocomplete', 'off');
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-expanded', 'false');

    input.addEventListener('input', function () {
      input.classList.remove('invalid');
      var q = input.value.trim();
      if (q.length < 2) { close(); return; }
      if (q === lastQuery) { return; }
      lastQuery = q;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fetch(buildUrl(input, q))
          .then(function (r) { return r.json(); })
          .then(render)
          .catch(close);
      }, 200);
    });

    input.addEventListener('keydown', function (e) {
      if (list.hidden || !items.length) { return; }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        cursor = (cursor + 1) % items.length;
        paint();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        cursor = (cursor - 1 + items.length) % items.length;
        paint();
      } else if (e.key === 'Enter' && cursor >= 0) {
        e.preventDefault();
        choose(cursor);
      } else if (e.key === 'Escape') {
        close();
      }
    });

    input.addEventListener('blur', function () { setTimeout(close, 120); });

    // 거주지를 바꾸면 근무지 추천 범위가 달라지므로 캐시를 비운다
    if (input.dataset.place === 'residence') {
      input.addEventListener('change', function () {
        var w = document.querySelector('input[data-place="workplace"]');
        if (w) { w.dataset.reset = '1'; }
      });
    }
    if (input.dataset.place === 'workplace') {
      input.addEventListener('focus', function () {
        if (input.dataset.reset) {
          lastQuery = '';
          delete input.dataset.reset;
        }
      });
    }
  }

  document.querySelectorAll('[data-combo]').forEach(setup);
})();
