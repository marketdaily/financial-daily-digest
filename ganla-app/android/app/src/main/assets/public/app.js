"use strict";

/* ===== 狀態 ===== */
const state = {
  players: JSON.parse(localStorage.getItem("ganla-players") || "[]"),
  soft: localStorage.getItem("ganla-soft") === "1",
  pendingGame: null,
  timers: [],
  timeouts: [],
};
const $ = (s) => document.querySelector(s);
const rand = (n) => Math.floor(Math.random() * n);
const pick = (a) => a[rand(a.length)];
const buzz = (ms) => { if (navigator.vibrate) navigator.vibrate(ms); };
function later(fn, ms) { const id = setTimeout(fn, ms); state.timeouts.push(id); return id; }
function savePlayers() { localStorage.setItem("ganla-players", JSON.stringify(state.players)); }
function drinkWord() { return state.soft ? "喝一口（或做一個大冒險）" : "喝一口"; }
function clearTimers() {
  state.timers.forEach(clearInterval); state.timers = [];
  state.timeouts.forEach(clearTimeout); state.timeouts = [];
}

/* ===== 音效引擎（Web Audio）===== */
const Sound = {
  ctx: null,
  on: localStorage.getItem("ganla-sound") !== "0",
  init() {
    if (!this.ctx) {
      try { this.ctx = new (window.AudioContext || window.webkitAudioContext)(); }
      catch (e) { return; }
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
  },
  tone(freq, dur, type = "sine", vol = 0.18, delay = 0) {
    if (!this.on || !this.ctx) return;
    const t = this.ctx.currentTime + delay;
    const o = this.ctx.createOscillator(), g = this.ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t);
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g); g.connect(this.ctx.destination);
    o.start(t); o.stop(t + dur + 0.02);
  },
  play(name) {
    if (!this.on) return;
    this.init();
    if (!this.ctx) return;
    switch (name) {
      case "click": this.tone(420, 0.05, "square", 0.08); break;
      case "tap":   this.tone(680, 0.05, "square", 0.1); break;
      case "good":  [523, 659, 784].forEach((f, i) => this.tone(f, 0.16, "sine", 0.16, i * 0.07)); break;
      case "win":   [523, 659, 784, 1047].forEach((f, i) => this.tone(f, 0.28, "triangle", 0.2, i * 0.1)); break;
      case "bad":   this.tone(180, 0.32, "sawtooth", 0.18); this.tone(120, 0.38, "sawtooth", 0.14, 0.05); break;
      case "bang":  this.tone(80, 0.45, "sawtooth", 0.32); for (let i = 0; i < 8; i++) this.tone(120 + rand(380), 0.1, "square", 0.1, i * 0.012); break;
      case "spin":  for (let i = 0; i < 14; i++) this.tone(900, 0.04, "square", 0.07, i * 0.085); break;
      case "tick":  this.tone(820, 0.04, "square", 0.08); break;
      case "dice":  for (let i = 0; i < 5; i++) this.tone(220 + rand(260), 0.06, "square", 0.1, i * 0.05); break;
      case "flip":  this.tone(540, 0.07, "sine", 0.1); this.tone(360, 0.1, "sine", 0.08, 0.05); break;
      case "pad0":  this.tone(330, 0.32, "sine", 0.18); break;
      case "pad1":  this.tone(440, 0.32, "sine", 0.18); break;
      case "pad2":  this.tone(550, 0.32, "sine", 0.18); break;
      case "pad3":  this.tone(660, 0.32, "sine", 0.18); break;
    }
  },
};

/* ===== 彩帶 ===== */
function confetti() {
  const colors = ["#f43f5e", "#fb923c", "#eab308", "#a855f7", "#3b82f6", "#22c55e", "#ec4899"];
  const wrap = document.createElement("div");
  wrap.className = "confetti";
  for (let i = 0; i < 40; i++) {
    const p = document.createElement("i");
    p.style.left = rand(100) + "%";
    p.style.background = pick(colors);
    p.style.animationDelay = (rand(45) / 100) + "s";
    p.style.animationDuration = (0.9 + rand(80) / 100) + "s";
    if (rand(2)) p.style.borderRadius = "50%";
    wrap.appendChild(p);
  }
  document.body.appendChild(wrap);
  setTimeout(() => wrap.remove(), 2800);
}

/* ===== 骰子點數 ===== */
const PIP_MAP = {1:[4],2:[0,8],3:[0,4,8],4:[0,2,6,8],5:[0,2,4,6,8],6:[0,2,3,5,6,8]};
function pips(v) {
  let h = "";
  for (let i = 0; i < 9; i++) h += `<div class="pip ${PIP_MAP[v].includes(i) ? "on" : ""}"></div>`;
  return h;
}
function cubeFaces() {
  let h = "";
  for (let v = 1; v <= 6; v++) h += `<div class="cube-face cf${v}">${pips(v)}</div>`;
  return h;
}
const FACE_ROT = {1:[0,0],2:[0,-90],3:[-90,0],4:[90,0],5:[0,90],6:[0,180]};
function rollCube(cube, val) {
  const [bx, by] = FACE_ROT[val];
  let cx = +(cube.dataset.x || 0), cy = +(cube.dataset.y || 0);
  cx += (3 + rand(3)) * 360 + (((bx - (cx % 360)) % 360) + 360) % 360;
  cy += (3 + rand(3)) * 360 + (((by - (cy % 360)) % 360) + 360) % 360;
  cube.dataset.x = cx; cube.dataset.y = cy;
  cube.style.transform = `rotateX(${cx}deg) rotateY(${cy}deg)`;
}

/* ===== 遊戲登錄（17 款）===== */
const GAMES = {
  command:    { emoji:"🎲", name:"派對指令",     desc:"抽指令卡，叫到誰誰就喝",       needPlayers:true,  min:2, start:startCommand },
  kings:      { emoji:"👑", name:"國王遊戲",     desc:"3D 翻牌，每張牌一條規則",       needPlayers:false,        start:startKings },
  truth:      { emoji:"🔥", name:"真心話大冒險", desc:"真心話或大冒險二選一",         needPlayers:false,        start:startTruth },
  mostlikely: { emoji:"🫵", name:"誰最有可能",   desc:"數到三一起指人，最多票喝",     needPlayers:false, isNew:true, start:startMostLikely },

  dice:       { emoji:"🎰", name:"7-8-9 骰子",   desc:"擲立體骰，看公杯怎麼喝",       needPlayers:false,        start:startDice },
  liardice:   { emoji:"🎲", name:"吹牛骰",       desc:"心機骰子，被開錯就喝",         needPlayers:true,  min:2, start:startLiarDice },
  roulette:   { emoji:"🎯", name:"命運轉盤",     desc:"立體轉盤隨機選人喝",           needPlayers:true,  min:2, start:startRoulette },
  password:   { emoji:"🔢", name:"終極密碼",     desc:"猜數字，猜中的人喝",           needPlayers:false,        start:startPassword },

  gun:        { emoji:"🔫", name:"俄羅斯輪盤",   desc:"六發一彈，中彈的喝",           needPlayers:false,        start:startGun },
  mine:       { emoji:"💣", name:"地雷陣",       desc:"輪流點格子，踩到地雷喝",       needPlayers:false, isNew:true, start:startMine },
  bomb:       { emoji:"🧨", name:"定時炸彈",     desc:"快傳手機，爆炸時拿著的喝",     needPlayers:false, isNew:true, start:startBomb },
  bottle:     { emoji:"🍾", name:"轉瓶子",       desc:"瓶口指到誰誰就接招",           needPlayers:true,  min:2, isNew:true, start:startBottle },

  reaction:   { emoji:"⚡", name:"手速王",       desc:"比反應速度，最慢的喝",         needPlayers:true,  min:2, isNew:true, start:startReaction },
  simon:      { emoji:"🧠", name:"記憶大考驗",   desc:"記住燈光順序，記錯就喝",       needPlayers:false, isNew:true, start:startSimon },
  rps:        { emoji:"✊", name:"猜拳擂台",     desc:"出拳贏電腦，輸了就喝",         needPlayers:false, isNew:true, start:startRPS },
  charades:   { emoji:"🎭", name:"比手畫腳",     desc:"限時演題，沒猜到就喝",         needPlayers:false,        start:startCharades },

  spy:        { emoji:"🕵️", name:"誰是臥底",     desc:"找出混進來的臥底",             needPlayers:true,  min:3, start:startSpy },
};

const CATS = [
  ["🎉 經典熱場", ["command", "kings", "truth", "mostlikely"]],
  ["🎲 骰子轉盤", ["dice", "liardice", "roulette", "password"]],
  ["💥 刺激運氣", ["gun", "mine", "bomb", "bottle"]],
  ["⚡ 反應對決", ["reaction", "simon", "rps", "charades"]],
  ["🕵️ 動腦推理", ["spy"]],
];

/* ===== 遊戲資料 ===== */
const COMMANDS = [
  { t:"{p} {d} 🍺", min:1 },
  { t:"{p} 乾杯！整杯乾掉 🥂", min:1 },
  { t:"{p} 選一個人幫你代喝", min:1 },
  { t:"{p} 學三秒貓叫，不像就 {d}", min:1 },
  { t:"{p} 十秒內講出三個台灣夜市，講不完就 {d}", min:1 },
  { t:"{p} 用台語講一句話，講不出來就 {d} 兩次", min:1 },
  { t:"{p} 唱五秒一首歌的副歌，荒腔走板就 {d}", min:1 },
  { t:"{p} 講一件自己最近的糗事，不講就 {d} 三次", min:1 },
  { t:"{p} 閉氣到下一張卡翻開，撐不住就 {d}", min:1 },
  { t:"{p} 模仿在場一個人，被猜中換他喝，沒人猜中 {p} {d}", min:1 },
  { t:"{p} 比一個性感動作，被全場噓就 {d}", min:1 },
  { t:"{p} 講出三個明星名字，重複或卡住就 {d}", min:1 },
  { t:"順時針，每個人 {d}", min:0 },
  { t:"逆時針，每個人 {d}", min:0 },
  { t:"全場男生 {d} 🍻", min:0 },
  { t:"全場女生 {d} 🍷", min:0 },
  { t:"最後一個把手放頭上的人，喝！", min:0 },
  { t:"最後一個站起來的人，喝！", min:0 },
  { t:"現在全場安靜，第一個說話的人喝", min:0 },
  { t:"戴眼鏡的人 {d}", min:0 },
  { t:"今天穿白色的人 {d}", min:0 },
  { t:"手機電量最低的人 {d}", min:0 },
  { t:"年紀最小的人 {d}", min:0 },
  { t:"年紀最大的人 {d}", min:0 },
  { t:"頭髮最長的人 {d}", min:0 },
  { t:"最後一個發限時動態的人 {d}", min:0 },
  { t:"全場一起乾一口，Cheers！🥂", min:0 },
  { t:"{p} 跟 {p2} 划拳，輸的 {d}", min:2 },
  { t:"{p} 跟 {p2} 喝交杯酒 🥰", min:2 },
  { t:"{p} 跟 {p2} 對看十秒，先笑的 {d}", min:2 },
  { t:"{p} 指定 {p2} 喝兩次", min:2 },
  { t:"{p} 跟 {p2} 比腕力，輸的 {d}", min:2 },
  { t:"{p} 跟 {p2} 同時喊一個數字，不一樣兩個都 {d}", min:2 },
  { t:"{p} 真心稱讚 {p2}，{p2} 沒臉紅 {p} 就 {d}", min:2 },
  { t:"{p}、{p2}、{p3} 一起乾杯", min:3 },
  { t:"{p} 在 {p2} 跟 {p3} 之間選一人代喝", min:3 },
];

const KING_RULES = {
  A:["瀑布","你開始喝，左手邊的人跟著喝、再下一個…你停大家才能停"],
  2:["指定","指定任何一人喝一口"],
  3:["我喝","抽到的人，自己喝一口"],
  4:["摸地板","所有人立刻摸地板，最慢的喝"],
  5:["男生喝","全場男生喝一口 🍻"],
  6:["女生喝","全場女生喝一口 🍷"],
  7:["摸天","所有人舉手指天，最慢的喝"],
  8:["找搭檔","選一個酒友，之後你喝他就要跟著喝"],
  9:["押韻","說一個詞，右邊的人接押韻，接不出來的喝"],
  10:["分類接龍","出一個類別（例：啤酒品牌），輪流接，卡住的喝"],
  J:["訂規則","你訂一條規則，到遊戲結束全場都要遵守，違規就喝"],
  Q:["問題大師","你是問題大師，任何人回答你的問題就要喝，直到下一張 Q"],
  K:["國王杯","倒一點你的酒進中央公杯；抽到第 4 張 K 的人，乾掉整杯！"],
};

const DICE_RULES = {
  2:["💥","兩個 1！指定一人乾杯"],
  3:["✅","安全，過"],
  4:["✅","安全，過"],
  5:["✅","安全，過"],
  6:["✅","安全，過"],
  7:["🫗","往中央公杯加酒（加多少你決定）"],
  8:["😬","喝掉公杯裡一半的酒"],
  9:["☠️","乾掉整個公杯！"],
  10:["✅","安全，過"],
  11:["🔄","換方向，下一棒換邊擲"],
  12:["🍻","兩個 6！全場一起喝"],
};

const TRUTHS = [
  "你做過最瘋狂的事是什麼？","在場你最想交換人生的人是誰？","你最近一次哭是為什麼？",
  "你手機裡有沒有不能被看的東西？","你暗戀過在場的人嗎？","你最丟臉的一次約會？",
  "你說過最大的謊是什麼？","你喝醉做過最蠢的事？","你前任最讓你受不了的點？",
  "你偷偷追蹤誰的社群？","你上次說「我沒事」其實有事，是什麼時候？","在場誰你第一眼覺得最難相處？",
  "你做過最對不起別人的事？","你最想刪掉的一段回憶？","你滑交友軟體嗎？最近一次配對對象？",
  "你最後一次傳曖昧訊息是給誰？","你最不想讓爸媽知道的事？","你嫉妒過在場的誰？為什麼？",
  "你的薪水/存款敢說出來嗎？","你今晚最想跟誰單獨聊聊？",
];
const DARES = [
  "打給通訊錄第 5 個人，唱生日快樂歌","讓右手邊的人翻你最近一則對話紀錄",
  "用台語跟在場最有魅力的人告白","模仿一個在場的人，直到被猜中",
  "學一分鐘嬰兒講話","發一則限時動態「我喝醉了」並維持一小時",
  "讓大家檢查你相簿最近三張照片","用屁股寫出你的名字",
  "跟左手邊的人深情對看 30 秒","講一個你真實的秘密，不能造假",
  "下一輪遊戲全程只能蹲著","讓全桌幫你取一個綽號，今晚都要叫它",
  "打開跟前任的對話框（可不送出）","表演五秒你最拿手的舞",
  "學三種動物叫，讓大家猜","把外套反過來穿到下一輪",
  "用最性感的聲音念一句菜單","讓對面的人用手指在你臉上畫一筆",
  "接下來三輪你說話都要加「喵」","跟隔壁桌的人要一張面紙",
];

const WORD_PAIRS = [
  ["珍珠奶茶","手搖紅茶"],["貓","老虎"],["籃球","排球"],["麥當勞","肯德基"],
  ["鋼琴","吉他"],["火鍋","燒烤"],["捷運","火車"],["海灘","游泳池"],
  ["啤酒","紅酒"],["蘋果","水梨"],["醫生","護理師"],["電影院","劇場"],
  ["太陽","月亮"],["雨傘","雨衣"],["牛排","豬排"],["飛機","高鐵"],
  ["微波爐","烤箱"],["牙刷","牙線"],["棒球","壘球"],["拖鞋","涼鞋"],
  ["巧克力","焦糖"],["沙發","床"],["耳機","喇叭"],["草莓","櫻桃"],
  ["夜市","商圈"],["颱風","地震"],["滑板","直排輪"],["咖啡","奶茶"],
  ["圍巾","帽子"],["鯊魚","鯨魚"],["相機","手機"],["可樂","汽水"],
];

const CHARADES = [
  ["游泳","動作"],["刷牙","動作"],["開車","動作"],["釣魚","動作"],["跳舞","動作"],
  ["彈吉他","動作"],["化妝","動作"],["爬山","動作"],["洗頭","動作"],["跳繩","動作"],
  ["綁鞋帶","動作"],["打籃球","動作"],["騎機車","動作"],["打麻將","動作"],["自拍","動作"],
  ["大象","動物"],["企鵝","動物"],["袋鼠","動物"],["猴子","動物"],["蛇","動物"],
  ["螃蟹","動物"],["兔子","動物"],["蜘蛛","動物"],["青蛙","動物"],["長頸鹿","動物"],
  ["蜘蛛人","角色"],["殭屍","角色"],["超人","角色"],["美人魚","角色"],["忍者","角色"],
  ["機器人","角色"],["吸血鬼","角色"],["哈利波特","角色"],
  ["喝醉","情境"],["失戀大哭","情境"],["求婚","情境"],["中樂透","情境"],["趕公車","情境"],
  ["打噴嚏","情境"],["睡覺打呼","情境"],["健身舉重","情境"],
];

const MOST_LIKELY = [
  "最有可能酒後傳訊息給前任","最有可能半夜還在嗑鹽酥雞","最有可能遲到",
  "最有可能變成有錢人","最有可能當網紅","最有可能先結婚",
  "最有可能在 KTV 搶麥","最有可能忘記自己說過的話","最有可能被詐騙",
  "最有可能裸辭去旅行","最有可能秒睡","最有可能一個人去看電影",
  "最有可能養十隻貓","最有可能成為派對主咖","最有可能喝醉哭",
  "最有可能偷吃宵夜被抓包","最有可能滑手機滑到沒電","最有可能談辦公室戀情",
  "最有可能中樂透馬上花光","最有可能在群組已讀不回","最有可能突然消失神隱",
  "最有可能把祕密說出去","最有可能為了愛情衝動","最有可能健身辦卡不去",
  "最有可能在這場最快醉","最有可能點最貴的那杯","最有可能明天宿醉請假",
  "最有可能跟陌生人聊整晚","最有可能對食物有要求","最有可能講話最大聲",
];

const RULES_BOOK = [
  ["🏓","啤酒乒乓 Beer Pong","長桌兩端各排 6～10 個杯子成金字塔，杯裡倒約 1/3 啤酒。兩隊輪流把乒乓球丟進對方杯中，被投進的杯子對方要喝掉並移走。先清光對方杯子的隊伍獲勝。"],
  ["🥢","敲敲杯","所有人圍圈輪流當莊家。莊家喊「敲敲杯啊～敲敲杯，敲這杯啊～敲這杯」，喊到「敲這杯」時大家持筷隨機敲一個杯子，跟莊家敲到同一杯的人乾掉那杯。"],
  ["✊","划拳","兩人同時出拳並喊數字（0～10）。喊中雙方出指總和者獲勝，輸的喝。經典喊法：兩好、五魁首、七巧、全部呼。"],
  ["🖐️","喊拳（0 與 5）","圍圈選一人當莊。每人用一隻手比「0」或「5」，莊家同時喊一個 5 的倍數。莊家喊中全場出指總和，莊家下家罰喝。"],
  ["💢","369","從 1 開始輪流報數，遇到含 3、6、9 的數字（3、6、9、13、16…）要拍手不能出聲。喊錯或拍錯的人喝，再從 1 開始。"],
  ["7️⃣","數七","輪流報數，遇到 7 的倍數或含 7 的數字要說「過」。出錯的人喝。"],
  ["❤️","心臟病","撲克牌平均發完，輪流翻牌並依序喊 A、2、3…翻出的牌與喊的數字相同時所有人搶拍牌堆，最慢的人收走全部牌。"],
  ["⚽","射龍門","翻兩張牌當「龍柱」，第三張若點數在兩柱之間＝射門成功不喝；落在門外或與龍柱同點（撞柱）＝失敗，喝。"],
  ["🃏","抽鬼牌","抽掉一張，剩下配對。輪流抽鄰座的牌，湊成對就丟出。最後留著鬼牌的人喝。"],
  ["📷","照相機（123 木頭人）","一人喊「照相機」並轉身，其他人動作定格。被喊到還在動的人喝。"],
  ["🏢","上樓梯下樓梯","圍圈每人指定一個樓層數。輪流喊「N 樓上 M 樓」「N 樓下 M 樓」，被叫到要立刻接，叫到空樓層、口誤或放空的人喝。"],
  ["👃","摸鼻子","所有人隨時可以默默摸自己的鼻子，其他人看到要跟著摸。最後一個摸鼻子的人喝。"],
];

/* ===== 畫面切換 ===== */
function show(id) {
  clearTimers();
  document.querySelectorAll(".screen").forEach((s) => (s.hidden = true));
  $("#screen-" + id).hidden = false;
  window.scrollTo(0, 0);
}

/* ===== 首頁（含分類）===== */
function renderHome() {
  const grid = $("#game-grid");
  grid.innerHTML = "";
  let order = 0;
  CATS.forEach(([catName, keys]) => {
    const head = document.createElement("div");
    head.className = "cat-head";
    head.textContent = catName;
    head.style.gridColumn = "1 / -1";
    grid.appendChild(head);
    keys.forEach((key) => {
      const g = GAMES[key];
      if (!g) return;
      const b = document.createElement("button");
      b.className = "game-tile";
      b.style.animationDelay = (order * 0.04) + "s";
      order++;
      b.innerHTML = `${g.isNew ? '<span class="gt-badge">新</span>' : ""}
        <div class="gt-emoji">${g.emoji}</div>
        <div class="gt-name">${g.name}</div>
        <div class="gt-desc">${g.desc}</div>`;
      b.onclick = () => { buzz(8); openGame(key); };
      grid.appendChild(b);
    });
  });
  updatePlayersBar();
  $("#soft-toggle").checked = state.soft;
  const sb = $("#sound-toggle");
  if (sb) sb.checked = Sound.on;
}

function updatePlayersBar() {
  const n = state.players.length;
  $("#players-bar-text").textContent =
    n ? `玩家：${state.players.join("、")}` : "設定玩家";
}

function openGame(key) {
  const g = GAMES[key];
  const min = g.min || 2;
  if (g.needPlayers && state.players.length < min) {
    state.pendingGame = key;
    $("#players-hint").textContent = `「${g.name}」至少需要 ${min} 位玩家，先加入名單`;
    renderPlayers();
    show("players");
    return;
  }
  startGame(key);
}

function startGame(key) {
  clearTimers();
  const g = GAMES[key];
  $("#game-title").textContent = g.emoji + " " + g.name;
  $("#game-stage").innerHTML = "";
  show("game");
  g.start();
}

/* ===== 玩家設定 ===== */
function renderPlayers() {
  const list = $("#player-list");
  list.innerHTML = "";
  if (!state.players.length) {
    list.innerHTML = `<div class="player-empty">還沒有玩家，加幾個人吧</div>`;
  }
  state.players.forEach((name, i) => {
    const chip = document.createElement("div");
    chip.className = "player-chip";
    chip.innerHTML = `<span></span><button aria-label="移除">✕</button>`;
    chip.firstChild.textContent = name;
    chip.querySelector("button").onclick = () => {
      state.players.splice(i, 1);
      savePlayers();
      renderPlayers();
    };
    list.appendChild(chip);
  });
}

function drawPlayers(n) {
  const pool = [...state.players];
  const out = [];
  for (let i = 0; i < n && pool.length; i++) out.push(pool.splice(rand(pool.length), 1)[0]);
  return out;
}

function stageCard(html) {
  const stage = $("#game-stage");
  stage.innerHTML = `<div class="stage-card fade-in">${html}</div>`;
  return stage.firstChild;
}

/* ===== 1. 派對指令 ===== */
function startCommand() {
  let round = 0;
  function next() {
    round++;
    const valid = COMMANDS.filter((c) => c.min <= state.players.length);
    const c = pick(valid);
    let text = c.t.replace(/\{d\}/g, drinkWord());
    const need = (c.t.match(/\{p\d?\}/g) || []).length;
    const ppl = drawPlayers(need);
    text = text.replace("{p3}", ppl[2]).replace("{p2}", ppl[1]).replace("{p}", ppl[0]);
    stageCard(`
      <div class="stage-tag">第 ${round} 回合</div>
      <div class="stage-emoji">🎲</div>
      <div class="stage-big">${text}</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="cmd-next">下一張 →</button>
      </div>`).querySelector("#cmd-next").onclick = () => { buzz(10); next(); };
  }
  next();
}

/* ===== 2. 國王遊戲 ===== */
function startKings() {
  let deck = [], kings = 0;
  const SUITS = [["♠","blk"],["♥","red"],["♦","red"],["♣","blk"]];
  const RANKS = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"];
  function reset() {
    deck = [];
    SUITS.forEach((s) => RANKS.forEach((r) => deck.push({ r, s: s[0], c: s[1] })));
    kings = 0;
  }
  function next() {
    if (!deck.length) reset();
    const c = deck.splice(rand(deck.length), 1)[0];
    const rule = KING_RULES[c.r];
    let extra = "";
    if (c.r === "K") {
      kings++;
      extra = kings >= 4
        ? `<div class="stage-sub" style="color:#f43f5e;font-weight:800">這是第 4 張 K！乾掉整杯公杯！</div>`
        : `<div class="stage-sub">已抽出 ${kings} 張 K（第 4 張要乾杯）</div>`;
    }
    const card = stageCard(`
      <div class="card3d">
        <div class="card3d-inner">
          <div class="face-back">🍻</div>
          <div class="face-front ${c.c === "red" ? "red" : ""}">
            <div class="card-corner">${c.r}<br>${c.s}</div>
            <div class="card-center">${c.s}</div>
            <div class="card-corner btm">${c.r}<br>${c.s}</div>
          </div>
        </div>
      </div>
      <div class="stage-tag">${rule[0]}</div>
      <div class="stage-big" style="font-size:20px">${rule[1]}</div>
      ${extra}
      <div class="stage-sub">牌堆剩 ${deck.length} 張</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="k-next">抽下一張 →</button>
      </div>`);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const el = card.querySelector(".card3d");
      if (el) { el.classList.add("flipped"); Sound.play("flip"); }
    }));
    if (c.r === "K" && kings >= 4) { later(() => { confetti(); Sound.play("bang"); }, 700); }
    card.querySelector("#k-next").onclick = () => { buzz(12); next(); };
  }
  reset();
  next();
}

/* ===== 3. 7-8-9 骰子 ===== */
function startDice() {
  function roll() {
    const d1 = rand(6) + 1, d2 = rand(6) + 1, sum = d1 + d2;
    const rule = DICE_RULES[sum];
    const dbl = d1 === d2 ? `<div class="stage-sub">對子！做完動作再擲一次</div>` : "";
    const card = stageCard(`
      <div class="dice3d">
        <div class="cube" id="cube1">${cubeFaces()}</div>
        <div class="cube" id="cube2">${cubeFaces()}</div>
      </div>
      <div class="stage-tag" id="d-tag">擲骰中…</div>
      <div class="stage-emoji" id="d-emoji" style="opacity:.2">🎲</div>
      <div class="stage-big" id="d-text" style="font-size:21px;opacity:.2">…</div>
      <div id="d-dbl"></div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="d-next" disabled>擲骰中…</button>
      </div>`);
    buzz(20); Sound.play("dice");
    requestAnimationFrame(() => requestAnimationFrame(() => {
      rollCube(card.querySelector("#cube1"), d1);
      rollCube(card.querySelector("#cube2"), d2);
    }));
    later(() => {
      card.querySelector("#d-tag").textContent = "總和 " + sum;
      const em = card.querySelector("#d-emoji");
      em.textContent = rule[0]; em.style.opacity = "1";
      const tx = card.querySelector("#d-text");
      tx.textContent = rule[1]; tx.style.opacity = "1";
      card.querySelector("#d-dbl").innerHTML = dbl;
      const b = card.querySelector("#d-next");
      b.disabled = false; b.textContent = "再擲一次 🎲";
      b.onclick = () => { buzz(12); roll(); };
      Sound.play("tap");
    }, 1150);
  }
  roll();
}

/* ===== 4. 吹牛骰 ===== */
function startLiarDice() {
  let rolls = [];
  function newRoll() {
    rolls = state.players.map(() => Array.from({ length: 5 }, () => rand(6) + 1));
    pass(0);
  }
  function pass(idx) {
    if (idx >= state.players.length) return ready();
    const name = state.players[idx];
    stageCard(`
      <div class="stage-tag">第 ${idx + 1} / ${state.players.length} 位</div>
      <div class="pass-emoji">📱</div>
      <div class="stage-big">把手機拿給<br>${name}</div>
      <div class="stage-sub">其他人別偷看螢幕</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="ld-see">我是 ${name}，看我的骰子</button>
      </div>`).querySelector("#ld-see").onclick = () => { buzz(10); Sound.play("dice"); reveal(idx); };
  }
  function reveal(idx) {
    const dice = rolls[idx].map((v) => `<div class="mini-die">${pips(v)}</div>`).join("");
    stageCard(`
      <div class="stage-tag">${state.players[idx]} 的骰子</div>
      <div class="secret-dice">${dice}</div>
      <div class="stage-sub">記住你的五顆骰子，喊注時用得到</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="ld-hide">藏好了，下一位 →</button>
      </div>`).querySelector("#ld-hide").onclick = () => { buzz(8); pass(idx + 1); };
  }
  function ready() {
    stageCard(`
      <div class="stage-emoji">🎲</div>
      <div class="stage-big">開始喊注！</div>
      <div class="stage-sub">輪流喊「N 個 X 點」，數量只能往上加。<br>覺得對方吹牛，就喊「開！」</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="ld-open">開盅！🔥</button>
      </div>`).querySelector("#ld-open").onclick = () => { buzz(20); Sound.play("good"); open(); };
  }
  function open() {
    const tally = [0,0,0,0,0,0,0];
    let rows = "";
    state.players.forEach((p, i) => {
      rolls[i].forEach((v) => tally[v]++);
      const d = rolls[i].map((v) => `<div class="mini-die">${pips(v)}</div>`).join("");
      rows += `<div class="dice-row-p"><div class="who">${p}</div><div class="mini-dice">${d}</div></div>`;
    });
    const tline = [1,2,3,4,5,6].map((v) => `${v}點×${tally[v]}`).join("　");
    stageCard(`
      <div class="stage-tag">開盅！</div>
      <div class="dice-grid">${rows}</div>
      <div class="spy-tally">${tline}</div>
      <div class="stage-sub">對照剛才的賭注，喊錯的人 ${drinkWord()}</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="ld-again">重新搖骰</button>
      </div>`).querySelector("#ld-again").onclick = () => { buzz(10); newRoll(); };
  }
  newRoll();
}

/* ===== 5. 俄羅斯輪盤 ===== */
function startGun() {
  let bullet, pos, survived, rot = 0;
  function load() { bullet = rand(6); pos = rand(6); survived = 0; }
  function chambersHTML() {
    let h = `<div class="cyl-core"></div>`;
    for (let i = 0; i < 6; i++) {
      const a = i * 60 * Math.PI / 180;
      const x = 105 + 64 * Math.sin(a), y = 105 - 64 * Math.cos(a);
      h += `<div class="chamber" style="left:${x}px;top:${y}px"></div>`;
    }
    return h;
  }
  function render(msg) {
    const card = stageCard(`
      <div class="stage-tag">俄羅斯輪盤</div>
      <div style="position:relative">
        <div class="gun-hammer"></div>
        <div class="cylinder" id="cyl" style="transform:rotate(${rot}deg)">${chambersHTML()}</div>
      </div>
      <div class="stage-sub" id="gun-msg">${msg || "六發子彈一發實彈，扣下扳機賭運氣"}</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="gun-pull">扣扳機 🔫</button>
      </div>`);
    card.querySelector("#gun-pull").onclick = () => pull(card);
  }
  function pull(card) {
    const btn = card.querySelector("#gun-pull");
    const cyl = card.querySelector("#cyl");
    btn.disabled = true;
    pos = (pos + 1) % 6;
    rot += 360 + (1 + rand(4)) * 60;
    cyl.style.transform = `rotate(${rot}deg)`;
    buzz(12); Sound.play("spin");
    later(() => {
      const msg = card.querySelector("#gun-msg");
      if (pos === bullet) {
        buzz([80,60,140]); Sound.play("bang");
        cyl.classList.add("flash-bang");
        card.classList.add("shake");
        msg.innerHTML = `💥 <b>砰！</b>中彈了 —— 持槍的人乾一杯！`;
        btn.textContent = "重新裝彈 🔄";
        btn.disabled = false;
        btn.onclick = () => { buzz(10); load(); render(); };
      } else {
        survived++;
        Sound.play("tick");
        msg.innerHTML = `喀…安全過關 ✓　已連續逃過 ${survived} 次，傳給下一個人`;
        btn.disabled = false;
      }
    }, 1100);
  }
  load();
  render();
}

/* ===== 6. 命運轉盤 ===== */
function startRoulette() {
  let rot = 0;
  const COLORS = ["#f43f5e","#fb923c","#eab308","#10b981","#06b6d4","#3b82f6","#a855f7","#ec4899"];
  function render() {
    const n = state.players.length, seg = 360 / n;
    const stops = [];
    let labels = "";
    for (let i = 0; i < n; i++) {
      const c = COLORS[i % COLORS.length];
      stops.push(`${c} ${(i * seg).toFixed(2)}deg ${((i + 1) * seg).toFixed(2)}deg`);
      const mid = i * seg + seg / 2;
      const flip = mid > 90 && mid < 270;
      labels += `<div class="wheel-label" style="transform:rotate(${mid}deg) translateY(-78px)">
        <span style="transform:rotate(${flip ? 180 : 0}deg)">${state.players[i]}</span></div>`;
    }
    const card = stageCard(`
      <div class="stage-tag">命運轉盤</div>
      <div class="wheel-wrap">
        <div class="wheel-pin"></div>
        <div class="wheel" id="wheel"
          style="background:conic-gradient(${stops.join(",")});transform:rotate(${rot}deg)">
          ${labels}<div class="wheel-hub"></div>
        </div>
      </div>
      <div class="stage-sub" id="wheel-msg">轉盤會隨機選一個人</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="spin">轉！</button>
      </div>`);
    const wheel = card.querySelector("#wheel");
    const btn = card.querySelector("#spin");
    btn.onclick = () => {
      btn.disabled = true;
      btn.textContent = "轉動中…";
      const win = rand(n), mid = win * seg + seg / 2;
      const target = ((-mid) % 360 + 360) % 360;
      const cur = ((rot % 360) + 360) % 360;
      rot += 360 * 6 + ((target - cur) % 360 + 360) % 360;
      wheel.style.transform = `rotate(${rot}deg)`;
      buzz(15); Sound.play("spin");
      later(() => {
        buzz([40,50,90]); Sound.play("good");
        card.querySelector("#wheel-msg").innerHTML =
          `<b>${state.players[win]}</b>，${drinkWord()}！🍻`;
        btn.disabled = false;
        btn.textContent = "再轉一次";
        btn.onclick = () => { buzz(10); render(); };
      }, 4500);
    };
  }
  render();
}

/* ===== 7. 終極密碼 ===== */
function startPassword() {
  let secret, lo, hi;
  function reset() { secret = rand(100) + 1; lo = 1; hi = 100; }
  function render(msg) {
    const c = stageCard(`
      <div class="stage-tag">終極密碼</div>
      <div class="stage-sub">範圍內輪流喊數字，喊中的人喝！</div>
      <div class="pw-range"><b>${lo}</b> ～ <b>${hi}</b></div>
      ${msg || ""}
      <form class="pw-form" id="pw-form">
        <input type="number" id="pw-input" inputmode="numeric" placeholder="${lo}-${hi}" />
        <button type="submit" class="btn btn-primary">猜</button>
      </form>`);
    c.querySelector("#pw-form").onsubmit = (e) => {
      e.preventDefault();
      const g = parseInt(c.querySelector("#pw-input").value, 10);
      if (isNaN(g) || g < lo || g > hi) return;
      if (g === secret) { buzz([30,40,80]); Sound.play("win"); confetti(); win(g); }
      else {
        buzz(15); Sound.play("tap");
        if (g < secret) lo = g + 1; else hi = g - 1;
        render(`<div class="stage-sub">${g} ${g < secret ? "太小" : "太大"}了！</div>`);
      }
    };
    c.querySelector("#pw-input").focus();
  }
  function win(g) {
    stageCard(`
      <div class="stage-emoji pop">💥</div>
      <div class="stage-big">猜中 ${g}！</div>
      <div class="stage-sub">喊中密碼的人，${drinkWord()}！</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="pw-again">再玩一局</button>
      </div>`).querySelector("#pw-again").onclick = () => { buzz(10); reset(); render(); };
  }
  reset();
  render();
}

/* ===== 8. 誰是臥底 ===== */
function startSpy() {
  let words = [], spyIdx = 0, idx = 0;
  function setup() {
    const pair = pick(WORD_PAIRS);
    spyIdx = rand(state.players.length);
    const civ = rand(2);
    words = state.players.map((_, i) => (i === spyIdx ? pair[1 - civ] : pair[civ]));
    idx = 0;
    pass();
  }
  function pass() {
    if (idx >= state.players.length) return discuss();
    const name = state.players[idx];
    stageCard(`
      <div class="stage-tag">第 ${idx + 1} / ${state.players.length} 位</div>
      <div class="pass-emoji">📱</div>
      <div class="stage-big">把手機拿給<br>${name}</div>
      <div class="stage-sub">輪到你才能看，其他人別偷看</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="sp-see">我是 ${name}，看我的詞</button>
      </div>`).querySelector("#sp-see").onclick = () => { buzz(10); reveal(); };
  }
  function reveal() {
    stageCard(`
      <div class="stage-tag">${state.players[idx]} 的祕密詞</div>
      <div class="secret-word">${words[idx]}</div>
      <div class="stage-sub">記住它，等等用一句話形容。<br>你也可能就是臥底 😏</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="sp-hide">記好了，藏起來 →</button>
      </div>`).querySelector("#sp-hide").onclick = () => { buzz(8); idx++; pass(); };
  }
  function discuss() {
    stageCard(`
      <div class="stage-emoji">🗣️</div>
      <div class="stage-big">開始描述！</div>
      <div class="stage-sub">每人輪流用「一句話」形容自己的詞，<br>不能直接講出來。聊完投票揪出臥底。</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="sp-vote">進入投票</button>
      </div>`).querySelector("#sp-vote").onclick = () => { buzz(10); vote(); };
  }
  function vote() {
    const btns = state.players
      .map((p, i) => `<button class="vote-btn" data-i="${i}">${p}</button>`).join("");
    const card = stageCard(`
      <div class="stage-tag">投票</div>
      <div class="stage-big" style="font-size:22px">誰是臥底？</div>
      <div class="stage-sub">全場討論後，選出最可疑的人</div>
      <div class="vote-list">${btns}</div>`);
    card.querySelectorAll(".vote-btn").forEach((b) => {
      b.onclick = () => { buzz(15); result(+b.dataset.i); };
    });
  }
  function result(acc) {
    const caught = acc === spyIdx;
    if (caught) { confetti(); Sound.play("win"); } else { Sound.play("bad"); }
    stageCard(`
      <div class="stage-emoji pop">${caught ? "🎯" : "😈"}</div>
      <div class="stage-big">${caught ? "抓到臥底了！" : "臥底逃脫成功！"}</div>
      <div class="stage-sub">臥底是 <b>${state.players[spyIdx]}</b>（拿到「${words[spyIdx]}」）<br>
        ${caught
          ? `臥底 ${state.players[spyIdx]}，${drinkWord()} 三次！`
          : `投票揪錯人，全場一起 ${drinkWord()}！`}</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="sp-again">再玩一局</button>
      </div>`).querySelector("#sp-again").onclick = () => { buzz(10); setup(); };
  }
  setup();
}

/* ===== 9. 比手畫腳 ===== */
function startCharades() {
  function intro() {
    stageCard(`
      <div class="pass-emoji">🎭</div>
      <div class="stage-big">把手機交給「演的人」</div>
      <div class="stage-sub">其他人先別看螢幕。<br>演的人看完題目，限時內比給大家猜。</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="ch-go">看題目（只有演的人看）</button>
      </div>`).querySelector("#ch-go").onclick = () => { buzz(10); play(); };
  }
  function play() {
    const [word, cat] = pick(CHARADES);
    let t = 40;
    const card = stageCard(`
      <div class="stage-tag">${cat}</div>
      <div class="charade-word">${word}</div>
      <div class="timer-num" id="ch-timer">${t}</div>
      <div class="stage-sub">用肢體演出來，限時內被猜到就贏</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="ch-win">✅ 猜對了</button>
        <button class="btn btn-soft" id="ch-fail">❌ 放棄（演的人喝）</button>
      </div>`);
    const tEl = card.querySelector("#ch-timer");
    const iv = setInterval(() => {
      if (!document.body.contains(tEl)) { clearInterval(iv); return; }
      t--;
      tEl.textContent = t;
      if (t <= 10) { tEl.classList.add("low"); Sound.play("tick"); }
      if (t <= 0) { clearInterval(iv); buzz([60,40,80]); Sound.play("bad"); result(false, word, true); }
    }, 1000);
    state.timers.push(iv);
    card.querySelector("#ch-win").onclick = () => { clearInterval(iv); buzz(20); Sound.play("good"); confetti(); result(true, word); };
    card.querySelector("#ch-fail").onclick = () => { clearInterval(iv); buzz(15); Sound.play("bad"); result(false, word); };
  }
  function result(win, word, timeup) {
    stageCard(`
      <div class="stage-emoji pop">${win ? "🎉" : "🍺"}</div>
      <div class="stage-big">${win ? "猜對了！" : timeup ? "時間到！" : "放棄了"}</div>
      <div class="stage-sub">${win
        ? "漂亮，換下一個人接著演"
        : `題目是「${word}」 —— 演的人，${drinkWord()}`}</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="ch-next">換人 / 下一題 →</button>
      </div>`).querySelector("#ch-next").onclick = () => { buzz(10); intro(); };
  }
  intro();
}

/* ===== 10. 真心話大冒險 ===== */
function startTruth() {
  function choose() {
    const c = stageCard(`
      <div class="stage-tag">真心話 大冒險</div>
      <div class="stage-emoji">🔥</div>
      <div class="stage-big" style="font-size:22px">選一個</div>
      <div class="td-choice">
        <button class="btn btn-lg btn-truth" id="t-truth">💙 真心話</button>
        <button class="btn btn-lg btn-dare" id="t-dare">🔥 大冒險</button>
      </div>`);
    c.querySelector("#t-truth").onclick = () => { buzz(10); reveal("truth"); };
    c.querySelector("#t-dare").onclick = () => { buzz(10); reveal("dare"); };
  }
  function reveal(type) {
    const isT = type === "truth";
    const text = pick(isT ? TRUTHS : DARES);
    stageCard(`
      <div class="stage-tag">${isT ? "真心話" : "大冒險"}</div>
      <div class="stage-emoji">${isT ? "💙" : "🔥"}</div>
      <div class="stage-big" style="font-size:21px">${text}</div>
      <div class="stage-sub">不做 / 不答的人，${drinkWord()}</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="td-next">換一題 / 換人 →</button>
      </div>`).querySelector("#td-next").onclick = () => { buzz(10); choose(); };
  }
  choose();
}

/* ===== 11. 地雷陣 ===== */
function startMine() {
  const SIZE = 12, BOMBS = 3;
  let bombs, safe;
  function reset() {
    bombs = new Set();
    while (bombs.size < BOMBS) bombs.add(rand(SIZE));
    safe = 0;
    render();
  }
  function render() {
    let tiles = "";
    for (let i = 0; i < SIZE; i++) tiles += `<button class="mine-tile" data-i="${i}">?</button>`;
    const card = stageCard(`
      <div class="stage-tag">地雷陣</div>
      <div class="stage-sub" id="mine-msg">輪流點一格，${BOMBS} 顆地雷藏在裡面</div>
      <div class="mine-grid">${tiles}</div>
      <div class="stage-sub" id="mine-foot">已安全排除 0 格</div>`);
    card.querySelectorAll(".mine-tile").forEach((t) => {
      t.onclick = () => tap(+t.dataset.i, t, card);
    });
  }
  function tap(i, t, card) {
    if (bombs.has(i)) {
      t.classList.add("boom"); t.textContent = "💥";
      buzz([80,60,140]); Sound.play("bang"); card.classList.add("shake");
      card.querySelector("#mine-msg").innerHTML = `💥 <b>踩到地雷！</b>點到的人，${drinkWord()}！`;
      card.querySelectorAll(".mine-tile").forEach((x) => {
        const xi = +x.dataset.i;
        if (bombs.has(xi) && xi !== i) { x.classList.add("boom"); x.textContent = "💣"; }
        x.disabled = true;
      });
      const foot = card.querySelector("#mine-foot");
      foot.innerHTML = `<button class="btn btn-primary btn-lg btn-block" id="mine-again">重新佈雷</button>`;
      foot.querySelector("#mine-again").onclick = () => { buzz(10); reset(); };
    } else {
      t.classList.add("safe"); t.textContent = "✓"; t.disabled = true;
      buzz(10); Sound.play("good"); safe++;
      card.querySelector("#mine-foot").textContent = "已安全排除 " + safe + " 格 —— 換下一個人";
      if (safe >= SIZE - BOMBS) {
        card.querySelector("#mine-msg").innerHTML = `😱 只剩地雷了！下一個人必死，乾脆 ${drinkWord()}`;
      }
    }
  }
  reset();
}

/* ===== 12. 定時炸彈 ===== */
function startBomb() {
  function render(msg) {
    const card = stageCard(`
      <div class="stage-tag">定時炸彈</div>
      <div class="bomb" id="bomb">🧨</div>
      <div class="stage-sub" id="bomb-msg">${msg || "點燃引信後快速傳遞，爆炸時手機在誰手上誰就喝"}</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="bomb-go">點燃引信 🔥</button>
      </div>`);
    card.querySelector("#bomb-go").onclick = () => ignite(card);
  }
  function ignite(card) {
    const bomb = card.querySelector("#bomb");
    const btn = card.querySelector("#bomb-go");
    const msg = card.querySelector("#bomb-msg");
    bomb.classList.add("lit");
    btn.disabled = true; btn.textContent = "快傳！別拿在手上 🔥";
    msg.textContent = "引信燃燒中…快把手機傳出去！";
    const fuse = 11000 + rand(15000);   // 11-26s
    const start = performance.now();
    let alive = true;
    function tick() {
      if (!alive || !document.body.contains(bomb)) return;
      const left = fuse - (performance.now() - start);
      if (left <= 0) { explode(card); return; }
      Sound.play("tick"); buzz(7);
      const next = Math.max(140, left / 9);
      later(tick, next);
    }
    tick();
    function explode(c) {
      alive = false;
      if (!document.body.contains(bomb)) return;
      Sound.play("bang"); buzz([100,60,160]);
      bomb.classList.remove("lit"); bomb.textContent = "💥";
      c.classList.add("shake");
      msg.innerHTML = `💥 <b>爆炸了！</b>現在手機在誰手上，誰就 ${drinkWord()}！`;
      btn.disabled = false; btn.textContent = "重新裝彈";
      btn.onclick = () => render();
    }
  }
  render();
}

/* ===== 13. 轉瓶子 ===== */
function startBottle() {
  let rot = 0;
  function render() {
    const n = state.players.length;
    let labels = "";
    for (let i = 0; i < n; i++) {
      const ang = i * (360 / n);
      labels += `<div class="ring-label" style="transform:rotate(${ang}deg) translateY(-104px)">
        <span style="transform:rotate(${-ang}deg)">${state.players[i]}</span></div>`;
    }
    const card = stageCard(`
      <div class="stage-tag">轉瓶子</div>
      <div class="bottle-wrap">
        <div class="bottle-ring">${labels}</div>
        <div class="bottle" id="bottle" style="transform:rotate(${rot}deg)">
          <div class="bottle-body"></div>
          <div class="bottle-neck"></div>
          <div class="bottle-cap"></div>
        </div>
      </div>
      <div class="stage-sub" id="bottle-msg">瓶口指到誰，誰就接招</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="bottle-spin">轉瓶子 🍾</button>
      </div>`);
    const bottle = card.querySelector("#bottle");
    const btn = card.querySelector("#bottle-spin");
    btn.onclick = () => {
      btn.disabled = true; btn.textContent = "轉動中…";
      Sound.play("spin"); buzz(15);
      const win = rand(n), ang = win * (360 / n);
      const cur = ((rot % 360) + 360) % 360;
      rot += 360 * 5 + (((ang - cur) % 360) + 360) % 360;
      bottle.style.transform = `rotate(${rot}deg)`;
      later(() => {
        buzz([40,50,90]); Sound.play("good");
        card.querySelector("#bottle-msg").innerHTML =
          `🍾 瓶口指向 <b>${state.players[win]}</b>！<br>${state.players[win]}，${drinkWord()} 或 接受真心話/大冒險`;
        btn.disabled = false; btn.textContent = "再轉一次";
        btn.onclick = () => render();
      }, 3700);
    };
  }
  render();
}

/* ===== 14. 手速王 ===== */
function startReaction() {
  let idx = 0, results = [];
  function pass() {
    if (idx >= state.players.length) return ranking();
    const name = state.players[idx];
    stageCard(`
      <div class="stage-tag">第 ${idx + 1} / ${state.players.length} 位</div>
      <div class="pass-emoji">⚡</div>
      <div class="stage-big">輪到 ${name}</div>
      <div class="stage-sub">綠燈一亮，立刻拍螢幕！搶快。<br>偷跑會被罰。</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="rx-start">準備好，開始</button>
      </div>`).querySelector("#rx-start").onclick = () => wait();
  }
  function wait() {
    const card = stageCard(`
      <div class="stage-tag">${state.players[idx]}</div>
      <div class="react-zone wait" id="rx-zone">準備…<div style="font-size:14px;font-weight:500;margin-top:6px">等綠燈，別偷跑</div></div>`);
    const zone = card.querySelector("#rx-zone");
    let armed = false, goTime = 0, done = false;
    const to = later(() => {
      if (done) return;
      armed = true; goTime = performance.now();
      zone.className = "react-zone go";
      zone.innerHTML = "拍！！！";
      Sound.play("good"); buzz(30);
    }, 1500 + rand(3000));
    zone.onclick = () => {
      if (done) return;
      done = true;
      if (!armed) { clearTimeout(to); Sound.play("bad"); buzz([50,40,60]); record(9999, true); }
      else { const ms = Math.round(performance.now() - goTime); Sound.play("tap"); buzz(15); record(ms, false); }
    };
  }
  function record(ms, jump) {
    results.push({ name: state.players[idx], ms, jump });
    const card = stageCard(`
      <div class="stage-emoji">${jump ? "🚫" : "⚡"}</div>
      <div class="stage-big">${jump ? "偷跑！" : state.players[idx]}</div>
      <div class="react-ms">${jump ? "犯規" : ms + " ms"}</div>
      <div class="stage-sub">${jump ? "犯規記為 9999ms" : ms < 250 ? "神反應！" : ms < 400 ? "不錯" : "再加油"}</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="rx-next">${idx + 1 >= state.players.length ? "看排名" : "下一位 →"}</button>
      </div>`);
    card.querySelector("#rx-next").onclick = () => { idx++; pass(); };
  }
  function ranking() {
    const sorted = [...results].sort((a, b) => a.ms - b.ms);
    const slow = sorted[sorted.length - 1];
    const rows = sorted.map((r, i) =>
      `<div class="${r === slow ? "slow" : ""}">
        <span>${i + 1}. ${r.name}</span>
        <span>${r.jump ? "偷跑犯規" : r.ms + " ms"}</span>
      </div>`).join("");
    const card = stageCard(`
      <div class="stage-tag">手速排名</div>
      <div class="react-rank">${rows}</div>
      <div class="stage-sub">最慢的 <b>${slow.name}</b>，${drinkWord()}！</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="rx-again">再比一次</button>
      </div>`);
    confetti(); Sound.play("win");
    card.querySelector("#rx-again").onclick = () => { idx = 0; results = []; pass(); };
  }
  pass();
}

/* ===== 15. 記憶大考驗 ===== */
function startSimon() {
  let seq = [], input = [], round = 0, locked = true;
  function nextRound() {
    round++; seq.push(rand(4)); input = [];
    render();
    flash();
  }
  function render() {
    const pads = [0,1,2,3].map((i) => `<button class="simon-pad sp${i}" data-i="${i}"></button>`).join("");
    const card = stageCard(`
      <div class="stage-tag">記憶大考驗</div>
      <div class="stage-sub" id="si-msg">看好燈光順序…</div>
      <div class="simon-grid">${pads}</div>
      <div class="stage-sub">第 ${round} 關 ・ 長度 ${seq.length}</div>`);
    card.querySelectorAll(".simon-pad").forEach((p) => {
      p.onclick = () => handle(+p.dataset.i, p);
    });
  }
  function flash() {
    locked = true;
    const pads = document.querySelectorAll(".simon-pad");
    seq.forEach((idx, k) => {
      later(() => {
        const p = pads[idx]; if (!p) return;
        p.classList.add("lit");
        Sound.play("pad" + idx);
        later(() => { if (p) p.classList.remove("lit"); }, 380);
      }, k * 580 + 450);
    });
    later(() => {
      locked = false;
      const m = $("#si-msg"); if (m) m.textContent = "換你！照順序點一遍";
    }, seq.length * 580 + 500);
  }
  function handle(idx, pad) {
    if (locked) return;
    pad.classList.add("lit");
    later(() => pad.classList.remove("lit"), 220);
    Sound.play("pad" + idx); buzz(8);
    input.push(idx);
    const k = input.length - 1;
    if (input[k] !== seq[k]) return fail();
    if (input.length === seq.length) {
      locked = true; buzz(20); Sound.play("good");
      later(nextRound, 650);
    }
  }
  function fail() {
    locked = true; buzz([60,40,80]); Sound.play("bad");
    stageCard(`
      <div class="stage-emoji pop">🧠💥</div>
      <div class="stage-big">記錯了！</div>
      <div class="stage-sub">撐到第 ${round} 關（長度 ${seq.length}）<br>記錯的人，${drinkWord()}</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="si-again">再玩一局</button>
      </div>`).querySelector("#si-again").onclick = () => {
      seq = []; round = 0; nextRound();
    };
  }
  nextRound();
}

/* ===== 16. 猜拳擂台 ===== */
function startRPS() {
  const HANDS = ["✊","✋","✌️"], NAMES = ["石頭","布","剪刀"];
  function choose() {
    const card = stageCard(`
      <div class="stage-tag">猜拳擂台</div>
      <div class="stage-emoji">🤖</div>
      <div class="stage-big" style="font-size:21px">出拳！贏電腦才安全</div>
      <div class="rps-row">
        <button class="rps-btn" data-h="0">✊</button>
        <button class="rps-btn" data-h="1">✋</button>
        <button class="rps-btn" data-h="2">✌️</button>
      </div>
      <div class="stage-sub">輸或平手就喝</div>`);
    card.querySelectorAll(".rps-btn").forEach((b) => {
      b.onclick = () => reveal(+b.dataset.h);
    });
  }
  function reveal(me) {
    const cpu = rand(3);
    const diff = (me - cpu + 3) % 3;
    const res = diff === 0 ? "tie" : diff === 1 ? "win" : "lose";
    const card = stageCard(`
      <div class="stage-tag">${NAMES[me]} vs ${NAMES[cpu]}</div>
      <div class="rps-vs">
        <span class="hand rps-shake">${HANDS[me]}</span>
        <span class="vs">VS</span>
        <span class="hand rps-shake">${HANDS[cpu]}</span>
      </div>
      <div class="stage-big">${res === "win" ? "你贏了！😎" : res === "lose" ? "你輸了 😵" : "平手 😐"}</div>
      <div class="stage-sub">${res === "win" ? "安全過關，換下一個人" : res === "lose" ? "輸的人，" + drinkWord() : "平手 —— 喝一口，再出一次"}</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="rps-next">${res === "win" ? "換人出拳 →" : "再出拳"}</button>
      </div>`);
    if (res === "win") { Sound.play("good"); confetti(); buzz(20); }
    else if (res === "lose") { Sound.play("bad"); buzz([50,40,70]); }
    else { Sound.play("tick"); buzz(12); }
    card.querySelector("#rps-next").onclick = () => choose();
  }
  choose();
}

/* ===== 17. 誰最有可能 ===== */
function startMostLikely() {
  function show1() {
    const q = pick(MOST_LIKELY);
    stageCard(`
      <div class="stage-tag">誰最有可能</div>
      <div class="stage-emoji">🫵</div>
      <div class="stage-big" style="font-size:23px">在場誰<br>${q}？</div>
      <div class="stage-sub">準備好，數到三一起指！</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="ml-go">3…2…1…指！</button>
      </div>`).querySelector("#ml-go").onclick = () => countdown(q);
  }
  function countdown(q) {
    let n = 3;
    const card = stageCard(`
      <div class="stage-tag">誰最有可能</div>
      <div class="point-count" id="ml-num">3</div>
      <div class="stage-big" style="font-size:20px">${q}？</div>`);
    Sound.play("tick"); buzz(25);
    const iv = setInterval(() => {
      const numEl = card.querySelector("#ml-num");
      if (!document.body.contains(numEl)) { clearInterval(iv); return; }
      n--;
      if (n > 0) {
        numEl.textContent = n; numEl.className = "point-count";
        // 強制重啟動畫
        void numEl.offsetWidth;
        numEl.style.animation = "none";
        requestAnimationFrame(() => { numEl.style.animation = ""; });
        Sound.play("tick"); buzz(25);
      } else if (n === 0) {
        numEl.textContent = "指！"; Sound.play("good"); buzz(80); confetti();
      } else {
        clearInterval(iv);
        result(q);
      }
    }, 800);
    state.timers.push(iv);
  }
  function result(q) {
    stageCard(`
      <div class="stage-emoji pop">👈</div>
      <div class="stage-big" style="font-size:21px">被指最多的人</div>
      <div class="stage-sub">${q}<br>—— 得票最高的，${drinkWord()}！<br>平手就一起喝</div>
      <div class="stage-actions">
        <button class="btn btn-primary btn-lg" id="ml-next">下一題 →</button>
      </div>`).querySelector("#ml-next").onclick = () => show1();
  }
  show1();
}

/* ===== 規則大全 ===== */
function renderRules() {
  const body = $("#rules-body");
  body.innerHTML = `<p class="hint">這些玩法需要實體道具或現場互動，App 收錄規則，照著玩就行。</p>`;
  RULES_BOOK.forEach(([emoji, title, desc]) => {
    const item = document.createElement("div");
    item.className = "rule-item";
    item.innerHTML = `
      <button class="rule-q">
        <span class="ri-emoji">${emoji}</span><span>${title}</span>
        <span class="ri-arrow">›</span>
      </button>
      <div class="rule-a"><p>${desc}</p></div>`;
    item.querySelector(".rule-q").onclick = () => item.classList.toggle("open");
    body.appendChild(item);
  });
}

/* ===== 事件綁定 ===== */
function bindEvents() {
  $("#age-yes").onclick = () => {
    Sound.init();
    localStorage.setItem("ganla-age-ok", "1");
    $("#age-gate").hidden = true;
    bootApp();
  };
  $("#age-no").onclick = () => {
    $("#age-gate").hidden = true;
    $("#age-block").hidden = false;
  };

  document.querySelectorAll("[data-go]").forEach((el) => {
    el.onclick = () => {
      const dest = el.dataset.go;
      if (dest === "rules") renderRules();
      if (dest === "home") renderHome();
      show(dest);
    };
  });
  $(".rules-card").onclick = () => { renderRules(); show("rules"); };

  $("#players-bar").onclick = () => {
    state.pendingGame = null;
    $("#players-hint").textContent = "加入今晚一起玩的人，部分遊戲會用到。";
    renderPlayers();
    show("players");
  };

  $("#multi-entry").onclick = () => { Sound.play("good"); buzz(10); Multi.enter(); };
  $("#multi-back").onclick = () => Multi.leave();

  $("#player-form").onsubmit = (e) => {
    e.preventDefault();
    const input = $("#player-input");
    const name = input.value.trim();
    if (name && !state.players.includes(name) && state.players.length < 16) {
      state.players.push(name);
      savePlayers();
      renderPlayers();
    }
    input.value = "";
    input.focus();
  };

  $("#players-done").onclick = () => {
    if (state.pendingGame) {
      const key = state.pendingGame, g = GAMES[key];
      if (g.needPlayers && state.players.length < (g.min || 2)) {
        renderHome(); show("home");
      } else {
        state.pendingGame = null;
        startGame(key);
      }
    } else {
      renderHome(); show("home");
    }
  };

  $("#soft-toggle").onchange = (e) => {
    state.soft = e.target.checked;
    localStorage.setItem("ganla-soft", state.soft ? "1" : "0");
  };
  const sb = $("#sound-toggle");
  if (sb) sb.onchange = (e) => {
    Sound.on = e.target.checked;
    localStorage.setItem("ganla-sound", Sound.on ? "1" : "0");
    if (Sound.on) { Sound.init(); Sound.play("good"); }
  };

  /* 全域按鈕音效 —— 排除自帶音效的遊戲按鈕 */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.closest(".simon-pad")) return;
    if (b.closest(".mine-tile")) return;
    if (b.classList.contains("rps-btn")) return;
    Sound.play("click");
  }, true);
}

/* =====================================================================
   多人連線（WebSocket 後端：ganla-rooms Cloudflare Worker + Durable Objects）
   ===================================================================== */
const API_BASE = "https://ganla-rooms.delvin-12345678.workers.dev";
const WS_BASE  = "wss://ganla-rooms.delvin-12345678.workers.dev";

const GAMES_MP = {
  dice:        { name: "多人搖骰" },
  niuniu:      { name: "妞妞" },
  dragon:      { name: "射龍門" },
  heartattack: { name: "心臟病" },
  oldmaid:     { name: "抽鬼牌" },
  tenhalf:     { name: "十點半" },
  bigtwo:      { name: "大老二" },
  redpts:      { name: "撿紅點" },
  chain:       { name: "接龍" },
};
const MP_PICK = [
  ["dice",        "🎲", "多人搖骰", "各自手機搖骰，最小的喝"],
  ["niuniu",      "🎴", "妞妞",     "5 張暗牌，亮牌比點數"],
  ["dragon",      "🐉", "射龍門",   "下注牌，跨距越大越賺"],
  ["heartattack", "❤️", "心臟病",   "即時搶拍，最慢的吃牌"],
  ["oldmaid",     "🃏", "抽鬼牌",   "輪流抽鄰座，鬼牌在誰手上誰喝"],
  ["tenhalf",     "💯", "十點半",   "比莊家近 10.5 分，輸的喝"],
  ["bigtwo",      "🂡", "大老二",   "單張/對子/三條/五張，先出完贏"],
  ["redpts",      "❤️", "撿紅點",   "配對收牌，紅心方塊最多贏"],
  ["chain",       "🪢", "接龍",     "輪流出下一個點數，沒牌就喝"],
];

const COMBO_NAMES = {
  single:"單張", pair:"對子", triple:"三條",
  straight:"順子", flush:"同花", full_house:"葫蘆",
  four_kicker:"鐵支", straight_flush:"同花順",
};
function rankLabel(r) {
  return r === 1 ? "A" : r === 11 ? "J" : r === 12 ? "Q" : r === 13 ? "K" : String(r);
}

function mpCardHTML(c) {
  if (!c) return `<div class="mp-card back">?</div>`;
  const red = c.c === "red";
  return `<div class="mp-card ${red ? "red" : ""}"><div class="lbl">${c.label}</div><div class="st">${c.s}</div></div>`;
}
function mpCardLabel(c) { return c ? `${c.label}${c.s}` : "?"; }

function evaluateNiuClient(cards) {
  if (!cards || cards.length < 5) return null;
  const v = cards.map((c) => Math.min(c.r, 10));
  for (let i = 0; i < 3; i++)
    for (let j = i + 1; j < 4; j++)
      for (let k = j + 1; k < 5; k++) {
        if ((v[i] + v[j] + v[k]) % 10 === 0) {
          const rest = v.reduce((s, x) => s + x, 0) - v[i] - v[j] - v[k];
          const niu = rest % 10;
          return { has: true, niu, rank: niu === 0 ? 11 : niu, name: niu === 0 ? "妞妞" : `妞 ${niu}` };
        }
      }
  return { has: false, niu: 0, rank: 0, name: "沒妞" };
}

const Multi = {
  ws: null,
  code: null,
  name: localStorage.getItem("ganla-name") || "",
  you: null,
  players: [],
  game: null,
  gs: null,
  hand: null,
  view: "lobby",
  pendingAfterName: null,

  enter() {
    if (this.ws && this.ws.readyState === 1) {
      this.view = this.game ? "game" : "room";
    } else {
      this.view = "lobby";
    }
    show("multi");
    this.render();
  },

  leave() {
    if (this.ws) { try { this.ws.close(); } catch {} }
    this.ws = null; this.code = null; this.you = null;
    this.players = []; this.game = null; this.gs = null; this.hand = null;
    this.view = "lobby";
    renderHome();
    show("home");
  },

  async createRoom() {
    if (!this.ensureName(() => this.createRoom())) return;
    try {
      const res = await fetch(API_BASE + "/api/rooms", { method: "POST" });
      const { code } = await res.json();
      this.connect(code, true);
    } catch (e) {
      this.showError("建立房間失敗：" + (e.message || e));
    }
  },

  joinRoom(code) {
    code = (code || "").toUpperCase().trim();
    if (!/^[A-Z2-9]{4}$/.test(code)) {
      this.showError("房號是 4 個字（英文＋數字，不含 0/1/O/I/L）");
      return;
    }
    if (!this.ensureName(() => this.joinRoom(code))) return;
    this.connect(code, false);
  },

  ensureName(cb) {
    if (this.name) return true;
    this.pendingAfterName = cb;
    this.view = "name";
    this.render();
    return false;
  },

  connect(code, asHost) {
    if (this.ws) { try { this.ws.close(); } catch {} }
    this.code = code;
    const params = `name=${encodeURIComponent(this.name)}${asHost ? "&host=1" : ""}`;
    const url = `${WS_BASE}/api/rooms/${code}/ws?${params}`;
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onmessage = (e) => this.onMessage(e.data);
    ws.onclose = () => {
      if (this.view === "room" || this.view === "game") {
        this.showError("連線中斷");
      }
      this.ws = null;
      this.view = "lobby";
      this.render();
    };
    ws.onerror = () => {};
  },

  onMessage(raw) {
    let m; try { m = JSON.parse(raw); } catch { return; }
    if (m.type === "welcome") {
      this.you = m.you; this.players = m.players;
      this.game = m.game; this.gs = m.gs; this.hand = null;
      this.view = m.game ? "game" : "room";
      Sound.play("good");
      this.render();
    } else if (m.type === "playerJoined" || m.type === "playerLeft") {
      this.players = m.players;
      Sound.play("tick");
      if (this.view === "room" || this.view === "game") this.render();
    } else if (m.type === "youAreHost") {
      if (this.you) this.you.isHost = true;
      this.render();
    } else if (m.type === "gameStarted") {
      this.game = m.game; this.gs = m.gs; this.hand = null;
      this.view = "game";
      Sound.play("win");
      this.render();
    } else if (m.type === "gameState") {
      this.game = m.game; this.gs = m.gs;
      this.render();
    } else if (m.type === "privateHand") {
      this.hand = m.hand;
      this.render();
    } else if (m.type === "gameEnded") {
      this.game = null; this.gs = null; this.hand = null;
      this.view = "room";
      this.render();
    } else if (m.type === "error") {
      this.showError(m.msg || "錯誤");
    }
  },

  send(msg) {
    if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(msg));
  },
  selectGame(game) { this.send({ type: "selectGame", game }); },
  exitGame()       { this.send({ type: "exitGame" }); },
  action(action, payload) { this.send({ type: "action", action, ...(payload || {}) }); },

  showError(msg) {
    const body = $("#multi-body");
    if (!body) return;
    const err = document.createElement("div");
    err.className = "stage-card fade-in";
    err.style.borderColor = "rgba(244,63,94,.5)";
    err.innerHTML = `<div class="stage-emoji">⚠️</div>
      <div class="stage-big" style="font-size:18px">${msg}</div>
      <div class="stage-actions"><button class="btn btn-primary btn-lg" id="err-ok">了解</button></div>`;
    body.prepend(err);
    err.querySelector("#err-ok").onclick = () => err.remove();
    Sound.play("bad"); buzz(40);
  },

  render() {
    const title = $("#multi-title");
    if (title) {
      title.textContent = this.view === "lobby" ? "多人連線"
        : this.view === "name"  ? "輸入暱稱"
        : this.view === "room"  ? `房間 ${this.code || ""}`
        : this.game ? GAMES_MP[this.game]?.name || "遊戲" : "遊戲";
    }
    if (this.view === "lobby") this.renderLobby();
    else if (this.view === "name") this.renderName();
    else if (this.view === "room") this.renderRoom();
    else if (this.view === "game") this.renderGame();
  },

  renderLobby() {
    $("#multi-body").innerHTML = `
      <p class="hint">跟朋友連線玩。沒帶撲克牌 / 骰子？App 幫你發牌、搖骰、發暗牌。</p>
      <button class="btn btn-primary btn-lg btn-block" id="mp-create">🪄 建立房間</button>
      <p class="hint" style="text-align:center;margin:8px 0 -2px">— 或 —</p>
      <form id="mp-join-form" class="player-form code-form">
        <input id="mp-code-input" maxlength="4" autocapitalize="characters" autocomplete="off" placeholder="房號" />
        <button type="submit" class="btn btn-primary">加入</button>
      </form>
      <p class="hint" style="margin-top:10px">建立後告訴朋友 4 個英數字房號，他們開 ganla.pages.dev 輸入即可加入。</p>
    `;
    $("#mp-create").onclick = () => this.createRoom();
    $("#mp-join-form").onsubmit = (e) => {
      e.preventDefault();
      this.joinRoom($("#mp-code-input").value);
    };
  },

  renderName() {
    $("#multi-body").innerHTML = `
      <p class="hint">起一個讓朋友認得的暱稱，最多 12 字。</p>
      <form class="name-form" id="mp-name-form">
        <input id="mp-name-input" maxlength="12" placeholder="你的暱稱…" autocomplete="off" />
        <button type="submit" class="btn btn-primary btn-lg btn-block">確定</button>
      </form>
    `;
    const input = $("#mp-name-input");
    input.value = this.name || "";
    setTimeout(() => input.focus(), 60);
    $("#mp-name-form").onsubmit = (e) => {
      e.preventDefault();
      const n = input.value.trim().slice(0, 12);
      if (!n) return;
      this.name = n;
      localStorage.setItem("ganla-name", n);
      const cb = this.pendingAfterName;
      this.pendingAfterName = null;
      if (cb) cb(); else { this.view = "lobby"; this.render(); }
    };
  },

  renderRoom() {
    const me = this.you;
    const playerHtml = this.players.map((p) =>
      `<div class="room-pill ${p.id === me?.id ? "me" : ""} ${p.isHost ? "host" : ""}">${p.name}</div>`
    ).join("");
    const games = `
      <div class="game-pick">
        ${MP_PICK.map(([k,e,n,d]) => `
          <button data-g="${k}">
            <span class="gp-emoji">${e}</span>
            <span class="gp-info"><strong>${n}</strong><span>${d}</span></span>
          </button>`).join("")}
      </div>`;
    $("#multi-body").innerHTML = `
      <div class="stage-card fade-in">
        <div class="stage-tag">房號</div>
        <div class="room-code">${this.code || ""}</div>
        <div class="room-code-hint">告訴朋友這 4 個字，他們就能加入</div>
      </div>
      <p class="hint">在場玩家（${this.players.length}）</p>
      <div class="room-players">${playerHtml}</div>
      ${me?.isHost
        ? `<p class="hint" style="margin-top:10px">👑 你是主機，選一款遊戲開始</p>${games}`
        : `<p class="hint" style="margin-top:10px">等主機選遊戲開始…</p>`}
      <button class="btn btn-soft btn-block" id="mp-leave" style="margin-top:12px">離開房間</button>
    `;
    $("#mp-leave").onclick = () => this.leave();
    if (me?.isHost) {
      document.querySelectorAll(".game-pick button").forEach((b) => {
        b.onclick = () => { Sound.play("good"); this.selectGame(b.dataset.g); };
      });
    }
  },

  renderGame() {
    const body = $("#multi-body");
    body.innerHTML = "";
    if (this.game === "dice") body.appendChild(this.renderDice());
    else if (this.game === "niuniu") body.appendChild(this.renderNiu());
    else if (this.game === "dragon") body.appendChild(this.renderDragon());
    else if (this.game === "heartattack") body.appendChild(this.renderHeart());
    else if (this.game === "oldmaid") body.appendChild(this.renderOldmaid());
    else if (this.game === "tenhalf") body.appendChild(this.renderTenhalf());
    else if (this.game === "bigtwo") body.appendChild(this.renderBigtwo());
    else if (this.game === "redpts") body.appendChild(this.renderRedpts());
    else if (this.game === "chain") body.appendChild(this.renderChain());

    if (this.you?.isHost) {
      const exit = document.createElement("button");
      exit.className = "btn btn-soft btn-block";
      exit.textContent = "結束遊戲，回房間";
      exit.style.marginTop = "12px";
      exit.onclick = () => this.exitGame();
      body.appendChild(exit);
    }
  },

  /* ----- 搖骰 ----- */
  renderDice() {
    const wrap = document.createElement("div");
    wrap.className = "stage-card fade-in";
    const me = this.you;
    const rolls = (this.gs && this.gs.rolls) || {};
    const myRolled = !!rolls[me.id];
    const allDone = this.gs?.phase === "done";
    const ranked = this.gs?.ranked || [];
    const winnerId = ranked[0]?.[0];
    const loserId  = ranked[ranked.length - 1]?.[0];
    let rowsHtml = "";
    this.players.forEach((p) => {
      const r = rolls[p.id];
      const cls = allDone ? (p.id === loserId ? "lose" : (p.id === winnerId ? "win" : "")) : "";
      const dice = (allDone && Array.isArray(r))
        ? `<div class="roll">${r.map((v) => `<div class="mp-mini-die">${v}</div>`).join("")} <span style="margin-left:6px;font-weight:900">${r[0] + r[1]}</span></div>`
        : `<div class="roll">${r ? "✅ 已搖" : "⏳ 等待"}</div>`;
      rowsHtml += `<div class="mp-dice-row ${cls}"><div class="who">${p.name}${p.id === me.id ? "（你）" : ""}</div>${dice}</div>`;
    });
    let action;
    if (allDone) {
      const loser = this.players.find((p) => p.id === loserId);
      action = `<div class="stage-big" style="font-size:20px">最小的 <b>${loser?.name || ""}</b>，${drinkWord()}！</div>
        ${me.isHost
          ? `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="mp-dice-again">再來一局</button></div>`
          : `<div class="stage-sub">等主機開新局…</div>`}`;
    } else if (myRolled) {
      action = `<div class="stage-sub">已搖，等其他人…</div>`;
    } else {
      action = `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="mp-dice-roll">搖骰 🎲</button></div>`;
    }
    wrap.innerHTML = `
      <div class="stage-tag">多人搖骰</div>
      <div class="mp-dice-grid">${rowsHtml}</div>
      ${action}`;
    const rollBtn = wrap.querySelector("#mp-dice-roll");
    if (rollBtn) rollBtn.onclick = () => { Sound.play("dice"); this.action("roll"); };
    const againBtn = wrap.querySelector("#mp-dice-again");
    if (againBtn) againBtn.onclick = () => this.action("newRound");
    if (allDone) confetti();
    return wrap;
  },

  /* ----- 妞妞 ----- */
  renderNiu() {
    const wrap = document.createElement("div");
    wrap.className = "stage-card fade-in";
    const me = this.you;
    const gs = this.gs || {};
    const myRevealed = gs.revealed?.[me.id];
    const allDone = gs.phase === "done";
    const ranked = gs.ranked || [];
    const winnerId = ranked[0]?.[0];
    const loserId  = ranked.length ? ranked[ranked.length - 1][0] : null;

    let othersHtml = "";
    this.players.forEach((p) => {
      if (p.id === me.id) return;
      const revealed = gs.revealed?.[p.id];
      const hand = gs.publicHands?.[p.id];
      const evalObj = allDone ? ranked.find(([pid]) => pid === p.id)?.[1] : null;
      const cls = allDone ? (p.id === loserId ? "lose" : (p.id === winnerId ? "win" : "")) : "";
      let handHtml;
      if (revealed && hand) {
        handHtml = `<div class="mp-niu-hand">${hand.map((c) => mpCardHTML(c)).join("")}</div>`;
      } else {
        handHtml = `<div class="mp-niu-hand">${'<div class="mp-card back">🍻</div>'.repeat(5)}</div>`;
      }
      othersHtml += `<div class="mp-niu-row ${cls}">
        <div class="niu-head"><span>${p.name}</span><span class="niu-name">${evalObj ? evalObj.name : (revealed ? "已亮" : "藏牌")}</span></div>
        ${handHtml}
      </div>`;
    });

    const myHand = this.hand || [];
    const myEval = allDone ? ranked.find(([pid]) => pid === me.id)?.[1] : null;
    const myEval0 = myHand.length === 5 ? evaluateNiuClient(myHand) : null;
    const myHandHtml = myHand.length
      ? `<div class="mp-my-hand">${myHand.map((c) => mpCardHTML(c)).join("")}</div>`
      : `<div class="stage-sub">等發牌…</div>`;

    let action;
    if (allDone) {
      const loser = this.players.find((p) => p.id === loserId);
      action = `<div class="stage-big" style="font-size:19px">最小的 <b>${loser?.name || ""}</b>，${drinkWord()}！${myEval ? `<br>你：<b>${myEval.name}</b>` : ""}</div>
        ${me.isHost
          ? `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="mp-niu-again">再來一局</button></div>`
          : `<div class="stage-sub">等主機重新發牌…</div>`}`;
    } else if (myRevealed) {
      action = `<div class="stage-sub">已亮牌（${myEval0?.name || ""}），等其他人亮…</div>`;
    } else {
      action = `
        <div class="stage-sub">你的牌：<b>${myEval0?.name || "…"}</b>。準備好就亮。</div>
        <div class="stage-actions">
          <button class="btn btn-primary btn-lg" id="mp-niu-reveal">亮牌！</button>
        </div>`;
    }

    wrap.innerHTML = `
      <div class="stage-tag">妞妞 ${allDone ? "・結算" : "・亮牌中"}</div>
      ${othersHtml}
      <p class="hint" style="margin:6px 0 -4px">你的手牌</p>
      ${myHandHtml}
      ${action}
    `;
    const rv = wrap.querySelector("#mp-niu-reveal");
    if (rv) rv.onclick = () => { Sound.play("good"); this.action("reveal"); };
    const ag = wrap.querySelector("#mp-niu-again");
    if (ag) ag.onclick = () => this.action("newRound");
    if (allDone && me.id === winnerId) confetti();
    return wrap;
  },

  /* ----- 射龍門 ----- */
  renderDragon() {
    const wrap = document.createElement("div");
    wrap.className = "stage-card fade-in";
    const me = this.you;
    const gs = this.gs || {};
    const turnPid = gs.turnPid;
    const myTurn = turnPid === me.id;
    const turnPlayer = this.players.find((p) => p.id === turnPid);

    const pillarsHtml = gs.pillars
      ? `<div class="mp-pillars">${mpCardHTML(gs.pillars[0])}<span class="mp-vs">⋯</span>${mpCardHTML(gs.pillars[1])}</div>`
      : `<div class="mp-pillars"><div class="mp-card back">?</div><span class="mp-vs">⋯</span><div class="mp-card back">?</div></div>`;

    const scores = Object.entries(gs.scores || {}).map(([pid, s]) => {
      const name = this.players.find((p) => p.id === +pid)?.name || "?";
      return `<span>${name}: ${s > 0 ? "+" : ""}${s}</span>`;
    }).join("");

    let resultHtml = "";
    if (gs.lastResult) {
      const r = gs.lastResult;
      const tname = this.players.find((p) => p.id === r.turnPid)?.name || "?";
      const resText = r.outcome === "win"
        ? `🎯 <b>射中！</b>${tname} 過關 —— 其他人 ${drinkWord()} ×${r.drinks}`
        : r.outcome === "post"
        ? `💥 <b>撞柱！</b>${tname} ${drinkWord()} ×${r.drinks}（雙倍）`
        : `❌ <b>失敗！</b>${tname} ${drinkWord()} ×${r.drinks}`;
      resultHtml = `<div class="stage-sub">上局：${resText}（翻出 ${mpCardLabel(r.card)}）</div>`;
    }

    let action;
    if (gs.phase === "deal") {
      action = myTurn
        ? `<div class="mp-turn-info">輪到你 —— 翻開兩張龍柱</div>
           <div class="stage-actions"><button class="btn btn-primary btn-lg" id="mp-dr-deal">翻龍柱 🐉</button></div>`
        : `<div class="mp-turn-info">輪到 <b>${turnPlayer?.name || "?"}</b> 翻牌…</div>`;
    } else if (gs.phase === "bet") {
      const a = Math.min(gs.pillars[0].r, gs.pillars[1].r);
      const b = Math.max(gs.pillars[0].r, gs.pillars[1].r);
      const gap = Math.max(0, b - a - 1);
      action = myTurn
        ? `<div class="mp-turn-info">下注幾杯？（兩柱中間有 ${gap} 個數字可中）</div>
           <div class="mp-bet-row" id="mp-bet-row">
             ${[1,2,3,4,5].map((n) => `<button data-b="${n}">${n}</button>`).join("")}
           </div>
           <button class="btn btn-soft btn-block" id="mp-dr-pass" style="margin-top:6px">略過這把</button>`
        : `<div class="mp-turn-info"><b>${turnPlayer?.name || "?"}</b> 正在下注…</div>`;
    } else if (gs.phase === "reveal") {
      action = myTurn
        ? `<div class="mp-turn-info">下注 ${gs.bet} 杯，翻第三張！</div>
           <div class="stage-actions"><button class="btn btn-primary btn-lg" id="mp-dr-reveal">翻開！🎴</button></div>`
        : `<div class="mp-turn-info"><b>${turnPlayer?.name || "?"}</b> 下注 ${gs.bet} 杯，等翻牌…</div>`;
    }

    wrap.innerHTML = `
      <div class="stage-tag">射龍門 ・ 剩 ${gs.deckCount} 張</div>
      ${pillarsHtml}
      ${resultHtml}
      ${action || ""}
      ${scores ? `<p class="hint" style="margin-top:8px">分數（純參考）</p><div class="mp-score-row">${scores}</div>` : ""}
      ${me.isHost ? `<button class="btn btn-soft btn-block" id="mp-dr-restart" style="margin-top:8px">重新洗牌</button>` : ""}
    `;
    const dealBtn   = wrap.querySelector("#mp-dr-deal");
    const passBtn   = wrap.querySelector("#mp-dr-pass");
    const revealBtn = wrap.querySelector("#mp-dr-reveal");
    const restartBtn= wrap.querySelector("#mp-dr-restart");
    if (dealBtn)   dealBtn.onclick   = () => { Sound.play("flip"); this.action("deal"); };
    if (passBtn)   passBtn.onclick   = () => this.action("pass");
    if (revealBtn) revealBtn.onclick = () => { Sound.play("flip"); this.action("reveal"); };
    if (restartBtn)restartBtn.onclick = () => this.action("newRound");
    const betRow = wrap.querySelector("#mp-bet-row");
    if (betRow) betRow.querySelectorAll("button").forEach((b) => {
      b.onclick = () => { Sound.play("tap"); this.action("bet", { bet: +b.dataset.b }); };
    });
    if (gs.lastResult && gs.lastResult.outcome === "win" && gs.lastResult.turnPid === me.id) confetti();
    return wrap;
  },

  /* ----- 心臟病（即時搶拍）----- */
  renderHeart() {
    const wrap = document.createElement("div");
    wrap.className = "stage-card fade-in";
    const gs = this.gs || {};
    const me = this.you;
    const myTurn = gs.turnPid === me.id;
    const isDone = gs.phase === "done";
    const isRace = gs.phase === "race";

    let stacksHtml = "";
    this.players.forEach((p) => {
      const count = (gs.stackCounts && gs.stackCounts[p.id]) || 0;
      const isCur = p.id === gs.turnPid && !isDone;
      const isLoser = isDone && gs.ultimateLoser === p.id;
      const cls = isLoser ? "lose" : (isCur && !isRace ? "win" : "");
      const status = count > 0 ? `📚 ${count} 張` : "✅ 安全";
      stacksHtml += `<div class="mp-dice-row ${cls}"><div class="who">${p.name}${p.id === me.id ? "（你）" : ""}${isCur && !isRace ? " 👉" : ""}</div><div class="roll">${status}</div></div>`;
    });

    const centerHtml = gs.centerTop
      ? `<div class="mp-pillars">${mpCardHTML(gs.centerTop)}</div><div class="stage-sub">中央 ${gs.centerCount} 張 ・ 喊「${gs.called}」</div>`
      : `<div class="stage-sub">尚未翻牌 ・ 開始喊「${gs.called || 1}」</div>`;

    let action;
    if (isDone) {
      const loser = this.players.find((p) => p.id === gs.ultimateLoser);
      action = `<div class="stage-big" style="font-size:20px">最後拿牌：<b>${loser?.name || "?"}</b>，${drinkWord()}！</div>
        ${me.isHost ? `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="ha-again">再來一局</button></div>` : ""}`;
    } else if (isRace) {
      const tappedNames = (gs.raceTapped || [])
        .map(([pid]) => this.players.find((p) => p.id === pid)?.name).filter(Boolean);
      const meTapped = (gs.raceTapped || []).find(([pid]) => pid === me.id);
      action = `<div class="stage-big" style="color:#f43f5e;font-size:22px">🚨 ${gs.centerTop?.label} = ${gs.called}！拍！</div>
        ${meTapped
          ? `<div class="stage-sub">你拍了 ✋ ・ 排序：${tappedNames.join(" → ")}</div>`
          : `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="ha-slap" style="font-size:24px;padding:24px">🖐️ 拍！</button></div>`}`;
    } else if (myTurn) {
      action = `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="ha-play">翻牌！喊「${gs.called}」</button></div>`;
    } else {
      const tp = this.players.find((p) => p.id === gs.turnPid);
      action = `<div class="mp-turn-info">輪到 <b>${tp?.name || "?"}</b> 翻牌，喊「${gs.called}」…</div>`;
    }

    wrap.innerHTML = `
      <div class="stage-tag">心臟病 ・ 喊 ${gs.called || 1}</div>
      ${centerHtml}
      ${action}
      <p class="hint">各玩家手牌</p>
      <div class="mp-dice-grid">${stacksHtml}</div>`;

    const playBtn = wrap.querySelector("#ha-play");
    if (playBtn) playBtn.onclick = () => { Sound.play("flip"); this.action("play"); };
    const slapBtn = wrap.querySelector("#ha-slap");
    if (slapBtn) slapBtn.onclick = () => { Sound.play("bang"); buzz(40); this.action("slap"); };
    const againBtn = wrap.querySelector("#ha-again");
    if (againBtn) againBtn.onclick = () => this.action("newRound");

    if (isRace && !((gs.raceTapped || []).find(([pid]) => pid === me.id))) buzz([60, 30, 60]);
    if (isDone && me.id !== gs.ultimateLoser) confetti();
    return wrap;
  },

  /* ----- 抽鬼牌 ----- */
  renderOldmaid() {
    const wrap = document.createElement("div");
    wrap.className = "stage-card fade-in";
    const gs = this.gs || {};
    const me = this.you;
    const myTurn = gs.turnPid === me.id;
    const isDone = gs.phase === "done";
    const turnPlayer = this.players.find((p) => p.id === gs.turnPid);

    // 找出抽誰的牌
    let giverPid = null;
    if (!isDone && gs.turnOrder && gs.handCounts) {
      const n = gs.turnOrder.length;
      let gi = (gs.turnOrder.indexOf(gs.turnPid) - 1 + n) % n;
      for (let k = 0; k < n; k++) {
        const cand = gs.turnOrder[gi];
        if (cand !== gs.turnPid && (gs.handCounts[cand] || 0) > 0) { giverPid = cand; break; }
        gi = (gi - 1 + n) % n;
      }
    }
    const giverPlayer = this.players.find((p) => p.id === giverPid);

    let othersHtml = "";
    this.players.forEach((p) => {
      if (p.id === me.id) return;
      const count = (gs.handCounts && gs.handCounts[p.id]) || 0;
      const isElim = (gs.eliminated || []).includes(p.id);
      const isLoser = isDone && gs.loser === p.id;
      const cls = isLoser ? "lose" : "";
      const arrow = p.id === gs.turnPid && !isDone ? " 👉" : p.id === giverPid && !isDone ? " 🎯" : "";
      const status = isElim ? "✅ 安全" : `${"🎴".repeat(Math.min(count, 6))} ${count} 張`;
      othersHtml += `<div class="mp-dice-row ${cls}"><div class="who">${p.name}${arrow}</div><div class="roll">${status}</div></div>`;
    });

    let lastHtml = "";
    if (gs.lastDraw) {
      const dr = this.players.find((p) => p.id === gs.lastDraw.drawerId);
      const gv = this.players.find((p) => p.id === gs.lastDraw.giverId);
      lastHtml = `<div class="stage-sub">上次：${dr?.name || "?"} 從 ${gv?.name || "?"} 抽了一張 —— ${gs.lastDraw.paired ? "✨ 配對成功，丟出" : "沒配到"}</div>`;
    }

    const myHand = this.hand || [];
    const myHandHtml = myHand.length
      ? `<div class="mp-niu-hand">${myHand.map((c) => mpCardHTML(c)).join("")}</div>`
      : `<div class="stage-sub">手上沒牌了 ✅ 安全</div>`;

    let action;
    if (isDone) {
      const loser = this.players.find((p) => p.id === gs.loser);
      action = `<div class="stage-big" style="font-size:21px">🃏 鬼牌在 <b>${loser?.name || "?"}</b> 手上，${drinkWord()}！</div>
        ${me.isHost ? `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="om-again">重新發牌</button></div>` : ""}`;
    } else if (myTurn) {
      action = `<div class="mp-turn-info">輪到你 —— 抽 <b>${giverPlayer?.name || "?"}</b> 的一張牌</div>
        <div class="stage-actions"><button class="btn btn-primary btn-lg" id="om-draw">抽一張 🎴</button></div>`;
    } else {
      action = `<div class="mp-turn-info">輪到 <b>${turnPlayer?.name || "?"}</b> 從 <b>${giverPlayer?.name || "?"}</b> 抽牌…</div>`;
    }

    wrap.innerHTML = `
      <div class="stage-tag">抽鬼牌</div>
      ${lastHtml}
      ${othersHtml ? `<p class="hint" style="margin:6px 0 -4px">其他玩家</p><div class="mp-dice-grid">${othersHtml}</div>` : ""}
      <p class="hint" style="margin:6px 0 -4px">你的手牌（${myHand.length}）</p>
      ${myHandHtml}
      ${action}`;

    const drawBtn = wrap.querySelector("#om-draw");
    if (drawBtn) drawBtn.onclick = () => { Sound.play("flip"); this.action("draw"); };
    const againBtn = wrap.querySelector("#om-again");
    if (againBtn) againBtn.onclick = () => this.action("newRound");

    if (isDone && me.id !== gs.loser) confetti();
    return wrap;
  },

  /* ----- 十點半 ----- */
  renderTenhalf() {
    const wrap = document.createElement("div");
    wrap.className = "stage-card fade-in";
    const gs = this.gs || {};
    const me = this.you;
    const iAmBanker = gs.bankerId === me.id;
    const isDone = gs.phase === "done";
    const isBankerPhase = gs.phase === "banker";

    const bankerPlayer = this.players.find((p) => p.id === gs.bankerId);
    const bankerHand = (gs.hands && gs.hands[gs.bankerId]) || [];
    const bankerScore = gs.scores ? gs.scores[gs.bankerId] : null;
    const bankerCardsHtml = bankerHand.map((c) => c?.hidden ? '<div class="mp-card back">?</div>' : mpCardHTML(c)).join("");

    let othersHtml = "";
    this.players.forEach((p) => {
      if (p.id === gs.bankerId) return;
      const h = (gs.hands && gs.hands[p.id]) || [];
      const sc = gs.scores ? gs.scores[p.id] : null;
      const stood = gs.stood && gs.stood[p.id];
      const bust = gs.bust && gs.bust[p.id];
      const result = gs.results?.results?.[p.id];
      const cls = result === "win" ? "win" : result === "lose" ? "lose" : "";
      const cardsHtml = h.map((c) => mpCardHTML(c)).join("");
      const statusText = isDone
        ? (result === "win" ? "🎉 贏" : result === "lose" ? "❌ 輸" : "🤝 平")
        : bust ? `💥 爆 ${sc}` : stood ? `🛑 停 ${sc}` : `${sc ?? ""}`;
      othersHtml += `<div class="mp-niu-row ${cls}"><div class="niu-head"><span>${p.name}${p.id === me.id ? "（你）" : ""}</span><span class="niu-name">${statusText}</span></div><div class="mp-niu-hand">${cardsHtml}</div></div>`;
    });

    let action;
    if (isDone) {
      const losers = this.players.filter((p) => p.id !== gs.bankerId && gs.results?.results?.[p.id] === "lose").map((p) => p.name);
      const winners = this.players.filter((p) => p.id !== gs.bankerId && gs.results?.results?.[p.id] === "win").map((p) => p.name);
      const bankerBust = gs.results?.bankerBust;
      let msg;
      if (bankerBust) msg = `💥 莊家 <b>${bankerPlayer?.name || "?"}</b> 爆了（${gs.results.bankerScore}）—— ${drinkWord()}！沒爆的玩家全贏`;
      else if (losers.length) msg = `莊家 <b>${bankerPlayer?.name}</b> ${gs.results.bankerScore} 分。輸的 ${drinkWord()}：${losers.join("、")}`;
      else if (winners.length) msg = `莊家 <b>${bankerPlayer?.name}</b> ${gs.results.bankerScore} 分。沒人輸 —— 莊家 ${drinkWord()}（自己一杯）`;
      else msg = `本局結束。`;
      action = `<div class="stage-big" style="font-size:18px">${msg}</div>
        ${me.isHost ? `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="th-again">重新發牌</button></div>` : ""}`;
    } else if (isBankerPhase) {
      if (iAmBanker) {
        const myScore = gs.scores?.[me.id];
        action = `<div class="mp-turn-info">輪到你（莊家）目前 <b>${myScore}</b> 分</div>
          <div class="stage-actions">
            <button class="btn btn-primary btn-lg" id="th-bhit">叫牌 +1</button>
            <button class="btn btn-soft" id="th-bstand">停牌</button>
          </div>`;
      } else {
        action = `<div class="mp-turn-info">莊家 <b>${bankerPlayer?.name || "?"}</b> 正在決定…</div>`;
      }
    } else {
      if (iAmBanker) {
        action = `<div class="mp-turn-info">你是莊家，等其他玩家叫牌/停牌…</div>`;
      } else {
        const myScore = gs.scores?.[me.id];
        const myStood = gs.stood?.[me.id];
        const myBust = gs.bust?.[me.id];
        if (myBust) action = `<div class="mp-turn-info">💥 你爆了（${myScore}），等其他人結束</div>`;
        else if (myStood) action = `<div class="mp-turn-info">🛑 已停牌（${myScore}），等莊家</div>`;
        else action = `<div class="mp-turn-info">你目前 <b>${myScore}</b> 分</div>
          <div class="stage-actions">
            <button class="btn btn-primary btn-lg" id="th-hit">叫牌 +1</button>
            <button class="btn btn-soft" id="th-stand">停牌</button>
          </div>`;
      }
    }

    wrap.innerHTML = `
      <div class="stage-tag">十點半 ${isBankerPhase ? "・莊家階段" : isDone ? "・結算" : "・玩家叫牌"}</div>
      <div class="mp-niu-row" style="background:linear-gradient(135deg,#a855f7,#3b82f6);border-color:transparent;color:#fff">
        <div class="niu-head"><span>👑 莊家 ${bankerPlayer?.name || ""}</span><span class="niu-name">${bankerScore == null ? "?" : bankerScore}</span></div>
        <div class="mp-niu-hand">${bankerCardsHtml}</div>
      </div>
      ${othersHtml ? `<p class="hint" style="margin:6px 0 -4px">玩家</p>${othersHtml}` : `<div class="stage-sub">需要至少 2 人玩</div>`}
      ${action}`;

    if (wrap.querySelector("#th-hit")) wrap.querySelector("#th-hit").onclick = () => { Sound.play("flip"); this.action("hit"); };
    if (wrap.querySelector("#th-stand")) wrap.querySelector("#th-stand").onclick = () => { Sound.play("tap"); this.action("stand"); };
    if (wrap.querySelector("#th-bhit")) wrap.querySelector("#th-bhit").onclick = () => { Sound.play("flip"); this.action("bankerHit"); };
    if (wrap.querySelector("#th-bstand")) wrap.querySelector("#th-bstand").onclick = () => { Sound.play("tap"); this.action("bankerStand"); };
    if (wrap.querySelector("#th-again")) wrap.querySelector("#th-again").onclick = () => this.action("newRound");

    if (isDone && gs.results?.results?.[me.id] === "win") confetti();
    return wrap;
  },

  btSelected: new Set(),

  /* ----- 大老二 ----- */
  renderBigtwo() {
    const wrap = document.createElement("div");
    wrap.className = "stage-card fade-in";
    const gs = this.gs || {};
    const me = this.you;
    const myTurn = gs.turnPid === me.id;
    const isDone = gs.phase === "done";

    let lastHtml = "";
    if (gs.lastPlay) {
      const player = this.players.find((p) => p.id === gs.lastPlay.playerId);
      const cards = gs.lastPlay.cards.map((c) => mpCardHTML(c)).join("");
      lastHtml = `<div class="stage-sub">上次：${player?.name || "?"} 出 <b>${COMBO_NAMES[gs.lastPlay.combo.type] || gs.lastPlay.combo.type}</b></div>
        <div class="mp-niu-hand">${cards}</div>`;
    } else if (!isDone) {
      lastHtml = `<div class="stage-sub">${gs.firstPlay ? "持 3♦ 的人先出牌" : "自由出牌（前一輪所有人都 PASS）"}</div>`;
    }

    let othersHtml = "";
    this.players.forEach((p) => {
      if (p.id === me.id) return;
      const count = gs.handCounts?.[p.id] ?? 0;
      const isCur = p.id === gs.turnPid && !isDone;
      const finishIdx = (gs.finishOrder || []).indexOf(p.id);
      const isLast = isDone && finishIdx === (gs.finishOrder.length - 1);
      const cls = isLast ? "lose" : (finishIdx >= 0 ? "win" : (isCur ? "win" : ""));
      const status = finishIdx >= 0 ? `🏆 第 ${finishIdx + 1}` : `${count} 張`;
      othersHtml += `<div class="mp-dice-row ${cls}"><div class="who">${p.name}${isCur ? " 👉" : ""}</div><div class="roll">${status}</div></div>`;
    });

    const myHand = this.hand || [];
    // 清掉超出範圍的 selected
    for (const i of [...this.btSelected]) if (i >= myHand.length) this.btSelected.delete(i);

    const handHtml = myHand.map((c, i) => {
      const sel = this.btSelected.has(i);
      return `<div class="mp-card bt-card ${c.c === "red" ? "red" : ""} ${sel ? "selected" : ""}" data-i="${i}"><div class="lbl">${c.label}</div><div class="st">${c.s}</div></div>`;
    }).join("");

    let action;
    if (isDone) {
      const ranks = (gs.finishOrder || []).map((pid, i) =>
        `<div class="${i === gs.finishOrder.length - 1 ? "slow" : ""}"><span>${i + 1}. ${this.players.find((p) => p.id === pid)?.name || "?"}</span><span>${i === 0 ? "🏆" : i === gs.finishOrder.length - 1 ? `${drinkWord()}` : ""}</span></div>`
      ).join("");
      action = `<div class="stage-big" style="font-size:19px">大老二結算</div>
        <div class="react-rank">${ranks}</div>
        ${me.isHost ? `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="bt-again">再來一局</button></div>` : ""}`;
      this.btSelected = new Set();
    } else if (myTurn) {
      action = `<div class="mp-turn-info">輪到你 ・ 點手牌選擇要出的，再按出牌</div>
        <div class="stage-actions">
          <button class="btn btn-primary btn-lg" id="bt-play">出 ${this.btSelected.size} 張</button>
          ${gs.lastPlay ? `<button class="btn btn-soft" id="bt-pass">PASS</button>` : ""}
        </div>`;
    } else {
      const tp = this.players.find((p) => p.id === gs.turnPid);
      action = `<div class="mp-turn-info">輪到 <b>${tp?.name || "?"}</b>… ${gs.passes ? `（已 ${gs.passes} 個 PASS）` : ""}</div>`;
    }

    wrap.innerHTML = `
      <div class="stage-tag">大老二</div>
      ${lastHtml}
      ${othersHtml ? `<p class="hint" style="margin:6px 0 -2px">其他玩家</p><div class="mp-dice-grid">${othersHtml}</div>` : ""}
      <p class="hint" style="margin:6px 0 -2px">你的手牌（${myHand.length}）</p>
      <div class="bt-hand">${handHtml || '<div class="stage-sub" style="width:100%">沒牌了 🏆</div>'}</div>
      ${action}`;

    wrap.querySelectorAll(".bt-card").forEach((card) => {
      card.onclick = () => {
        const i = +card.dataset.i;
        if (this.btSelected.has(i)) this.btSelected.delete(i);
        else this.btSelected.add(i);
        Sound.play("tap"); buzz(6);
        this.render();
      };
    });
    const playBtn = wrap.querySelector("#bt-play");
    if (playBtn) playBtn.onclick = () => {
      const cards = [...this.btSelected].sort((a, b) => a - b);
      if (!cards.length) return;
      Sound.play("flip");
      this.action("play", { cards });
      this.btSelected = new Set();
    };
    const passBtn = wrap.querySelector("#bt-pass");
    if (passBtn) passBtn.onclick = () => { Sound.play("tap"); this.action("pass"); };
    const againBtn = wrap.querySelector("#bt-again");
    if (againBtn) againBtn.onclick = () => { this.btSelected = new Set(); this.action("newRound"); };

    if (isDone && gs.finishOrder?.[0] === me.id) confetti();
    return wrap;
  },

  /* ----- 撿紅點 ----- */
  renderRedpts() {
    const wrap = document.createElement("div");
    wrap.className = "stage-card fade-in";
    const gs = this.gs || {};
    const me = this.you;
    const myTurn = gs.turnPid === me.id;
    const isDone = gs.phase === "done";

    const tableHtml = (gs.table || []).length
      ? `<div class="mp-niu-hand">${gs.table.map((c) => mpCardHTML(c)).join("")}</div>`
      : `<div class="stage-sub">桌面空</div>`;

    let lastHtml = "";
    if (gs.lastEvent) {
      const e = gs.lastEvent;
      const player = this.players.find((p) => p.id === e.player);
      const matched = e.matched.length;
      const drawnText = e.drawn
        ? ` ・ 翻 ${e.drawn.label}${e.drawn.s}${e.drawnMatched ? ` → 收 ${e.drawnMatched + 1} 張` : "，留桌"}`
        : "";
      lastHtml = `<div class="stage-sub">${player?.name || "?"} 出 ${e.played.label}${e.played.s}${matched ? ` → 收 ${matched + 1} 張` : "，留桌"}${drawnText}</div>`;
    }

    let othersHtml = "";
    this.players.forEach((p) => {
      const count = gs.handCounts?.[p.id] ?? 0;
      const red = gs.redCounts?.[p.id] || 0;
      const total = gs.pileCounts?.[p.id] || 0;
      const isCur = p.id === gs.turnPid && !isDone;
      const myRank = (gs.results || []).findIndex((r) => r.pid === p.id);
      const cls = isDone && myRank === 0 ? "win" : isDone && myRank === gs.results.length - 1 ? "lose" : "";
      othersHtml += `<div class="mp-dice-row ${cls}"><div class="who">${p.name}${p.id === me.id ? "（你）" : ""}${isCur ? " 👉" : ""}</div><div class="roll">❤️ ${red} ・ 手 ${count} ・ 收 ${total}</div></div>`;
    });

    const myHand = this.hand || [];
    const myHandHtml = myHand.map((c, i) =>
      `<div class="mp-card ${c.c === "red" ? "red" : ""}" data-i="${i}" style="${myTurn && !isDone ? "cursor:pointer" : "opacity:.7"}"><div class="lbl">${c.label}</div><div class="st">${c.s}</div></div>`
    ).join("");

    let action;
    if (isDone) {
      const winner = gs.results[0];
      const loser = gs.results[gs.results.length - 1];
      const winName = this.players.find((p) => p.id === winner.pid)?.name;
      const loseName = this.players.find((p) => p.id === loser.pid)?.name;
      action = `<div class="stage-big" style="font-size:19px">🏆 紅點王 <b>${winName}</b>（${winner.red} 紅）<br>最少 <b>${loseName}</b>（${loser.red} 紅），${drinkWord()}</div>
        ${me.isHost ? `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="rp-again">再來一局</button></div>` : ""}`;
    } else if (myTurn) {
      action = `<div class="mp-turn-info">輪到你 ・ 點手牌出一張</div>`;
    } else {
      const tp = this.players.find((p) => p.id === gs.turnPid);
      action = `<div class="mp-turn-info">輪到 <b>${tp?.name || "?"}</b>…</div>`;
    }

    wrap.innerHTML = `
      <div class="stage-tag">撿紅點 ・ 牌堆剩 ${gs.deckCount}</div>
      <p class="hint" style="margin:6px 0 -2px">桌面</p>
      ${tableHtml}
      ${lastHtml}
      <p class="hint" style="margin:6px 0 -2px">玩家</p>
      <div class="mp-dice-grid">${othersHtml}</div>
      <p class="hint" style="margin:6px 0 -2px">你的手牌（${myHand.length}）</p>
      <div class="mp-myhand">${myHandHtml || '<div class="stage-sub" style="width:100%">沒牌了</div>'}</div>
      ${action}`;

    if (myTurn && !isDone) {
      wrap.querySelectorAll(".mp-myhand .mp-card").forEach((card) => {
        card.onclick = () => { Sound.play("flip"); this.action("play", { cardIdx: +card.dataset.i }); };
      });
    }
    const againBtn = wrap.querySelector("#rp-again");
    if (againBtn) againBtn.onclick = () => this.action("newRound");
    if (isDone && gs.results?.[0]?.pid === me.id) confetti();
    return wrap;
  },

  /* ----- 接龍 ----- */
  renderChain() {
    const wrap = document.createElement("div");
    wrap.className = "stage-card fade-in";
    const gs = this.gs || {};
    const me = this.you;
    const myTurn = gs.turnPid === me.id;
    const isDone = gs.phase === "done";

    const centerHtml = gs.centerTop
      ? `<div class="mp-pillars">${mpCardHTML(gs.centerTop)}</div>`
      : `<div class="mp-pillars"><div class="mp-card back">起手</div></div>`;
    const expectLabel = gs.expectRank == null ? "任意" : rankLabel(gs.expectRank);

    let othersHtml = "";
    this.players.forEach((p) => {
      const count = gs.handCounts?.[p.id] ?? 0;
      const isCur = p.id === gs.turnPid && !isDone;
      const finishIdx = (gs.finishOrder || []).indexOf(p.id);
      const isWin = finishIdx === 0 && gs.finishOrder.length > 0;
      const isLast = isDone && finishIdx === gs.finishOrder.length - 1;
      const cls = isLast ? "lose" : isWin ? "win" : "";
      const skips = gs.skips?.[p.id] || 0;
      const status = finishIdx >= 0 ? `🏆 第 ${finishIdx + 1}` : `${count} 張${skips ? ` ・ 跳 ${skips}` : ""}`;
      othersHtml += `<div class="mp-dice-row ${cls}"><div class="who">${p.name}${p.id === me.id ? "（你）" : ""}${isCur ? " 👉" : ""}</div><div class="roll">${status}</div></div>`;
    });

    const myHand = this.hand || [];
    const canIdx = new Set();
    myHand.forEach((c, i) => {
      if (gs.expectRank == null || c.r === gs.expectRank) canIdx.add(i);
    });
    const myHandHtml = myHand.map((c, i) =>
      `<div class="mp-card ${c.c === "red" ? "red" : ""}" data-i="${i}" style="${canIdx.has(i) && myTurn && !isDone ? "cursor:pointer" : "opacity:.4"}"><div class="lbl">${c.label}</div><div class="st">${c.s}</div></div>`
    ).join("");

    let action;
    if (isDone) {
      const winName = this.players.find((p) => p.id === gs.finishOrder[0])?.name;
      const loseName = this.players.find((p) => p.id === gs.finishOrder[gs.finishOrder.length - 1])?.name;
      action = `<div class="stage-big" style="font-size:19px">🏆 第一名 <b>${winName}</b><br>最後 <b>${loseName}</b>，${drinkWord()}</div>
        ${me.isHost ? `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="ch-again">再來一局</button></div>` : ""}`;
    } else if (myTurn) {
      const canPlay = canIdx.size > 0;
      action = `<div class="mp-turn-info">輪到你 ・ 出 <b>${expectLabel}</b>${canPlay ? "（點下方該牌）" : "，沒牌就跳過"}</div>
        ${canPlay ? "" : `<div class="stage-actions"><button class="btn btn-primary btn-lg" id="ch-skip">沒牌，跳過 ${drinkWord()}</button></div>`}`;
    } else {
      const tp = this.players.find((p) => p.id === gs.turnPid);
      action = `<div class="mp-turn-info">輪到 <b>${tp?.name || "?"}</b>，要出 <b>${expectLabel}</b>…</div>`;
    }

    wrap.innerHTML = `
      <div class="stage-tag">接龍 ・ 下張要 <b>${expectLabel}</b></div>
      ${centerHtml}
      <p class="hint" style="margin:6px 0 -2px">玩家</p>
      <div class="mp-dice-grid">${othersHtml}</div>
      <p class="hint" style="margin:6px 0 -2px">你的手牌（${myHand.length}）</p>
      <div class="mp-myhand">${myHandHtml || '<div class="stage-sub" style="width:100%">沒牌了 🏆</div>'}</div>
      ${action}`;

    if (myTurn && !isDone) {
      wrap.querySelectorAll(".mp-myhand .mp-card").forEach((card) => {
        const i = +card.dataset.i;
        if (canIdx.has(i)) {
          card.onclick = () => { Sound.play("flip"); this.action("play", { cardIdx: i }); };
        }
      });
    }
    const skipBtn = wrap.querySelector("#ch-skip");
    if (skipBtn) skipBtn.onclick = () => { Sound.play("bad"); buzz(40); this.action("skip"); };
    const againBtn = wrap.querySelector("#ch-again");
    if (againBtn) againBtn.onclick = () => this.action("newRound");
    if (isDone && gs.finishOrder?.[0] === me.id) confetti();
    return wrap;
  },
};

/* ===== 啟動 ===== */
function bootApp() {
  $("#app").hidden = false;
  renderHome();
  show("home");
}

function init() {
  bindEvents();
  if (localStorage.getItem("ganla-age-ok") === "1") {
    $("#age-gate").hidden = true;
    bootApp();
  }
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }
}
init();
