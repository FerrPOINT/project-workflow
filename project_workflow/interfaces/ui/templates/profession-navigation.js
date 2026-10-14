// Local profession selection and platform project identity have different owners.
(() => {
  const url = new URL(window.location.href);
  const legacy = url.searchParams.getAll('namespace_id');
  if (!url.searchParams.has('registry_instance_id') && !url.searchParams.has('profession_id') &&
      legacy.length === 1 && /^[1-9]\d*$/.test(legacy[0])) {
    url.searchParams.set('profession_id', legacy[0]);
    url.searchParams.delete('namespace_id');
    window.SdlcPlatformNavigation.syncRoute(url.toString(), true);
  }
  const withProjectContext = value => {
    const target = new URL(value, window.location.href);
    const source = new URLSearchParams(window.location.search);
    for (const key of ['registry_instance_id', 'namespace_id', 'project_scope']) {
      target.searchParams.delete(key);
      for (const item of source.getAll(key)) target.searchParams.append(key, item);
    }
    return target.toString();
  };
  window.WorkflowNavigation = {
    withProjectContext,
    preserveProjectContext() {
      document.querySelectorAll('a[href]').forEach(link => {
        if (link.hasAttribute('download')) return;
        let target;
        try { target = new URL(link.href, window.location.href); } catch { return; }
        if (!['http:', 'https:'].includes(target.protocol)) return;
        if (target.origin !== window.location.origin && !link.classList.contains('service-menu-item')) return;
        link.href = withProjectContext(target.toString());
      });
    },
  };
})();
