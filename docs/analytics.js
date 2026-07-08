/* PostHog 分析 — 轉換漏斗(landing→註冊→登入→Premium)。
   純附加,不碰既有 DOM;失敗一律靜默,絕不影響網站功能。
   輸入值預設遮罩(PostHog 只記元素 metadata 不記密碼/email 內容)。 */
!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException loadToolbar get_property getSessionProperty createPersonProfile opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
try {
  posthog.init('phc_CJhrtgVt6Q6Q8Rh9ctNbZBFyPdsbNF6fPzLpnHByvxTm', {
    api_host: 'https://us.i.posthog.com',
    person_profiles: 'identified_only',
    capture_pageview: true,
    disable_session_recording: true
  });
} catch (e) {}

/* 全站通用埋點 helper:任何頁面呼叫 window.mdTrack('event', {props}) 即可,掛掉靜默 */
window.mdTrack = function (ev, props) {
  try { if (window.posthog && posthog.capture) posthog.capture(ev, props || {}); } catch (e) {}
};
/* 用 email 綁定使用者身分(登入/註冊成功後呼叫),讓漏斗跨裝置對齊 */
window.mdIdentify = function (email) {
  try { if (email && window.posthog && posthog.identify) posthog.identify(email); } catch (e) {}
};
