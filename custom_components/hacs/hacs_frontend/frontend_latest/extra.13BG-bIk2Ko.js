const e="ha-main-window",o=(()=>{try{return window.name===e?window:parent.name===e?parent:top}catch{return window}})(),a=(e,o)=>((e,o,a,n)=>{n=n||{},a=null==a?{}:a;const t=new Event(o,{bubbles:void 0===n.bubbles||n.bubbles,cancelable:Boolean(n.cancelable),composed:void 0===n.composed||n.composed});return t.detail=a,e.dispatchEvent(t),t})(e,"hass-notification",o);(()=>{const e=o?.document?.querySelector("home-assistant"),n=e?.hass;e.___hacs_reload_handler_active||(n?(e.___hacs_reload_handler_active=!0,n.connection.subscribeEvents((()=>{a(e,{duration:3e5,dismissable:!1,message:"[HACS] You need to reload your browser",action:{action:()=>{o.location.href=o.location.href},text:"reload"}})}),"hacs_resources_updated")):console.error("[HACS/extra/reload_handler] hass not found"))})();
//# sourceMappingURL=extra.13BG-bIk2Ko.js.map