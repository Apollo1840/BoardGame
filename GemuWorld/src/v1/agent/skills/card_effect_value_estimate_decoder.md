# 效果估值解码器

本文档定义如何把标准效果码转换为数值。完整流程见 [`card_effect_value_estimate.md`](card_effect_value_estimate.md)，效果码的编写方法见 [`card_effect_value_estimate_encoder.md`](card_effect_value_estimate_encoder.md)。

本文档依次给出：

1. 核心锚点；
2. 理论估值方法；
3. 按效果类型的分析与例子；
4. 计算速查表；
5. 标准计算流程。

---

## 1. 核心锚点

以下事件是整套估值体系的主要数值锚点。表中数值均为完全兑现、没有状态修正时的基础理论价值 $B(E)$。

| 锚点事件 | 基础理论价值 | 直观含义 |
|:--|:--|:--|
| $\text{DMG}(5)$ | $1$ | 5点信仰约值1 |
| $\text{HC}(1)$ | $1$ | 抽1张牌约值1 |
| $\text{HC}(-1)$ | $-0.5$ | 自选弃1张牌约值-0.5 |
| $\text{MANA}(1,1,1)$ | $1$ | 我方选择我方目标获得1灵力约值1 |
| $\text{FC}(1,1,1)$ | $3$ | 凭空增加1张我方场牌约值3 |
| $\text{AK}(1,1,1)$ | $1$ | 我方选择我方怪物获得1次额外行动约值1 |

其余基础效果以这些锚点、目标选择差异和经验系数推导。

---

## 2. 理论估值方法

### 2.1 基础理论价值与实际估值

- $B(E)$：效果完全兑现时的基础理论价值。
- $V(E)$：经过状态存在概率和实现系数修正后的实际估值。

对直接事件：

$$
V(E)=P(S_E)\cdot q(E)\cdot B(E)
$$

若事件没有必要状态，取 $P(S_E)=1$；若未注明实现系数，取 $q(E)=1$。

### 2.2 基础公理

| 规则 | 公式 |
|:--|:--|
| 非负重复 | $B(nE)=nB(E),\ n\ge0$ |
| 方向翻转 | $B(-E)=-B(E)$ |
| 效果叠加 | $B(E_1+E_2)=B(E_1)+B(E_2)$ |
| 实际估值 | $V(E)=P(S_E)q(E)B(E)$ |
| 条件复合 | $V(\text{Cond}_T(E_a)+G)=p(T)V(G^-)+\max(C(T;E_a)+V(G^+),0)$ |

条件价值代理使用独立的锚点价值：

$$
A(E_a)=q_a(E_a)B(E_a)
$$

其中 $q_a(E_a)>0$ 是条件锚点实现系数，默认取1。$A(E_a)$ 不乘 $P(S_{E_a})$，因为真实触发事件是否发生已经由 $p(T)$ 计算。

条件价值为：

$$
k(p)=\sqrt{\frac{1-p}{p}},\qquad 0<p\le1
$$

$$
C(T;E_a)=
\begin{cases}
0 & A(E_a)=0\\
-5 & p(T)=0,\ A(E_a)\ne0\\
-\min\left(5,k(p(T))|A(E_a)|\right) & 0<p(T)\le1
\end{cases}
$$

$T$ 是真实触发事件，$E_a=\rho(T)$ 是编码器给出的条件价值代理。$k(p)$ 使用触发概率的胜算比平方根；$p(T)=1$ 时 $k(p)=0$，因此确定性事件没有条件垫付。条件垫付绝对值上限为5。$p(T)=0$ 且锚点非零时，未封顶系数视为正无穷，应用上限后条件价值为 $-5$。

必须区分：

- $nE$：同一事件非负重复 $n$ 次。
- $E(x)$：事件参数为 $x$；其价值由该事件的基础价值函数决定，不保证关于正负参数线性。
- $-E$：交换事件的玩家视角，不等同于把参数 $x$ 改成 $-x$。

因此，$\text{HC}(-1)$ 可以按弃牌规则估值为 $-0.5$，而不必等于 $-\text{HC}(1)$ 的价值。

### 2.3 吉姆博弈价值函数

用于 `TargetAct` 事件，反映目标所属方和选择权的不对称性：

$$
v_{\alpha,\beta}(i,j,x)=
\begin{cases}
j\cdot\max(\alpha x,\alpha\beta x) & i,j\text{同号}\\
j\cdot\min(\alpha x,\alpha\beta x) & i,j\text{异号}
\end{cases}
$$

- $\alpha$：模块的基础价值尺度。
- $\beta$：不利目标选择带来的缓冲系数。
- $i,j\in\{1,-1\}$：$1$ 为我方，$-1$ 为对方。

| 模块 | $\alpha$ | $\beta$ |
|:--|:--|:--|
| 场牌 $\text{FC}$ | 3 | 0.5 |
| 灵力 $\text{MANA}$ | 1 | 0.5 |
| 攻击/防御 | 0.2 | 0.5 |
| 行动 $\text{AK}$ | 1 | 0.5 |
| 怪物能力消除 $\text{CLEAN.M}$ | 0.5 | 0.5 |
| 预言效果消除 $\text{CLEAN.P}$ | 1.5 | 0.5 |
| 攻击/效果免疫 $\text{TOL.ATK},\text{TOL.EFK}$ | 0.5 | 0.5 |
| 防止战斗破坏 $\text{TOL.ATK.sur}$ | 0.4 | 0.5 |
| 防止效果破坏 $\text{TOL.EFK.sur}$ | 0 | 0.5 |

### 2.4 `TargetAct` 通用后缀

令模块 $X$ 的基础价值尺度为 $\alpha_X$，令 $n_X$ 为该类全体目标的期望数量。统一规定：

$$
n_{\text{monster}}=1.5,\qquad
n_{\text{prophecy}}=1.5,\qquad
n_{\text{field}}=n_{\text{cover}}=n_{\text{monster}}+n_{\text{prophecy}}=3.
$$

盖牌不计入 $n_{\text{field}}$：盖牌与手牌统一由 $\text{HC}$ 抽象；覆盖预言卡属于盖牌，不属于 $\text{FC.P}$。没有专门条目覆盖时：

| 后缀 | 基础理论价值 | 含义 |
|:--|:--|:--|
| $X.\text{self}(x)$ | $0.9\alpha_Xx$ | 仅作用于自身 |
| $X.\text{rand}(j,x)$ | $0.8j\alpha_Xx$ | $j$ 方发生无玩家自由选择目标、总等效量为 $x$ 的变化 |
| $X.\text{each}(j,x)$ | $n_Xj\alpha_Xx$ | $j$ 方所有合法对象各变化 $x$；按对象类型选择 $n_X$ |

随机或全体效果没有目标选择权，因此效果码只保留受影响方 $j$ 与变化量 $x$。发动者及真实触发语义由卡效上下文或条件事件 $T$ 保留，不进入该基础价值签名。`.rand` 中的 $x$ 是整个代理效果的总等效变化量；如果目标数量本身影响价值，编码器必须保留多个事件而不能只合并 $x$。

模块尺度为：

$$
\alpha_{\text{FC}}=3,\quad
\alpha_{\text{MANA}}=1,\quad
\alpha_{\text{V.ATK}}=\alpha_{\text{V.DEF}}=0.2,\quad
\alpha_{\text{AK}}=1,\quad
\alpha_{\text{CLEAN.M}}=0.5,\quad
\alpha_{\text{CLEAN.P}}=1.5
$$

专门条目优先于通用规则。多个后缀的组合若没有专门条目，暂不自动相乘。

随机、全体与双方全体的短写：

$$
X.\text{rand}(x):=X.\text{rand}(1,x)
$$

$$
X.\text{each}(x):=X.\text{each}(1,x)
$$

$$
X.\text{all}(x):=
X.\text{each}(1,x)+X.\text{each}(-1,x)
$$

`.each` 永远表示某一方的全部合法对象；`.all` 表示双方全部合法对象。“全场”必须根据实际含义选择其中之一。

由此可得：

| 事件 | 基础理论价值 |
|:--|:--|
| $\text{V.ATK.rand}(j,x),\text{V.DEF.rand}(j,x)$ | $0.16jx$ |
| $\text{V.DEF.lock}(x)$ | $0.3x$ |
| $\text{V.ATK.each}(j,x),\text{V.DEF.each}(j,x)$ | $0.3jx$ |
| $\text{FC.rand}(j,x),\text{FC.M.rand}(j,x),\text{FC.P.rand}(j,x)$ | $2.4jx$ |
| $\text{FC.each}(j,x)$ | $9jx$ |
| $\text{FC.M.each}(j,x),\text{FC.P.each}(j,x)$ | $4.5jx$ |
| $\text{AK.rand}(j,x)$ | $0.8jx$ |
| $\text{AK.each}(j,x)$ | $1.5jx$ |
| $\text{CLEAN.M.rand}(n)$ | $0.4n$ |
| $\text{CLEAN.P.rand}(n)$ | $1.2n$ |
| $\text{CLEAN.M.each}(n)$ | $0.75n$ |
| $\text{CLEAN.P.each}(n)$ | $2.25n$ |
| $\text{CLEAN.M.each.const}(n)$ | $1.125n$ |
| $\text{CLEAN.P.each.const}(n)$ | $3.375n$ |

未带 $j$ 的普通 `.rand(x)` 是 `.rand(1,x)` 的短写。`CLEAN.M` 与 `CLEAN.P` 的 `.rand`、`.each` 是专门短写，参数 $n\ge0$ 分别表示被消除的怪物能力数量和预言效果数量，默认目标为对方，不使用通用目标后缀的我方目标展开。

### 2.5 状态条件 $\text{Cond}_\text{has}$

$$
V(\text{Cond}_\text{has}(S)*E)=P(S)\cdot q(E)\cdot B(E)
$$

- $P(S)$：效果起效所需状态存在的概率。
- $q(E)$：效果起效后实际落地的程度。
- 二者可以同时使用；通常 $q(E)=1$。

双对象效果必须按合法目标门槛修正。若必须同时存在两个对象，使用 $P(\text{S.X}(j,\ge2))$；若“至多两个”且单目标也能结算，应把第一对象与第二对象拆开，分别使用 $P(\ge1)$ 与 $P(\ge2)$，不能直接按 $2B(E)$ 完全兑现。两个对象类型不同时，应使用二者状态同时成立的联合概率。

状态谓词使用独立的 `S.` 命名空间，不与效果事件共用签名。

| 状态 $S$ | 含义 | 默认 $P(S)$ |
|:--|:--|:--|
| $\text{S.FC.M}(1,\ge1)$ | 我方场上有怪物 | 0.9 |
| $\text{S.FC.M}(1,\ge2)$ | 我方场上有2只怪物 | 0.5 |
| $\text{S.FC.M}(-1,\ge1)$ | 对方场上有怪物 | 0.9 |
| $\text{S.FC.M}(-1,\ge2)$ | 对方场上有2只怪物 | 0.5 |
| $\text{S.HC.M}(1,\ge1)$ | 我方手牌有怪物 | 0.9 |
| $\text{S.HC}(-1,\ge1)$ | 对方有手牌 | 0.9 |
| $\text{S.Deck.M}(1,\ge1)$ | 我方牌堆有怪物卡 | 1 |

#### 阈值谓词

当效果事件作为 `Cond` 的条件价值代理并包含阈值时，使用使条件成立的最小边界值计算：

$$
B(X(\ge k)):=B(X(k)),
\qquad
B(X(\le-k)):=B(X(-k)),
\qquad k>0
$$

例如：

$$
B(\text{DMG}(\le-5))=B(\text{DMG}(-5))=-1
$$

边界值只确定条件价值代理的估值锚点；当回合内发生一次的概率仍由真实触发事件的 $p(T)$ 表示。`Cond_has` 内使用 `S.` 状态谓词，其概率直接由 $P(S)$ 给出，不调用基础事件价值。

### 2.6 事件条件 $\text{Cond}$

对于“当真实事件 $T$ 发生时，执行效果 $G$”，编码器提供条件价值代理 $E_a=\rho(T)$。解码器不解释 $T$ 与 $E_a$ 的游戏语义关系，只使用独立锚点价值：

$$
A(E_a)=q_a(E_a)B(E_a)
$$

$q_a(E_a)>0$，默认取1。锚点不乘 $P(S_{E_a})$；真实事件发生所需的状态与时机已经包含在 $p(T)$ 中。

然后计算：

$$
V(\text{Cond}_T(E_a)+G)
=
p(T)V(G^-)
+
\max\left(C(T;E_a)+V(G^+),0\right)
$$

其中将条件后的效果按我方视角拆分为：

$$
G=G^++G^-
$$

- $G^+$ 包含该条件节点内的全部正向收益，满足 $V(G^+)\ge0$；
- $G^-$ 包含文本中真实存在的代价、损耗、敌方收益及其他负向效果，满足 $V(G^-)\le0$；
- $G^-$ 只有在真实触发事件发生后才会执行，因此必须使用 $p(T)V(G^-)$ 进行触发概率矫正；
- 条件垫付只抵扣 $G^+$，最多将正向收益抵扣至0。未抵完的垫付作废，不形成负价值，也不向条件节点外溢出；
- 该下限只保护正向收益，不保护真实负向效果，因此整条效果的最终估值仍然可以小于0。

- $p(T)$ 是真实触发事件 $T$ 在相关当回合内自然发生一次的概率。
- $A(E_a)$ 是条件价值代理的独立锚点价值，用于确定处罚尺度。
- 不根据一局中的预期触发次数追加乘数。
- 条件处罚有意压低触发式效果估值，使其可以容纳更高的正面效果。
- 条件垫付的绝对值上限为5。

$$
k(p)=\sqrt{\frac{1-p}{p}},\qquad 0<p\le1
$$

$$
C(T;E_a)=
\begin{cases}
0 & A(E_a)=0\\
-5 & p(T)=0,\ A(E_a)\ne0\\
-\min\left(5,k(p(T))|A(E_a)|\right) & 0<p(T)\le1
\end{cases}
$$

$p(T)=1$ 时 $k(p)=0$，条件价值自然为0。$p(T)=0$ 且锚点非零时，胜算比平方根趋于正无穷，但条件垫付最终封顶为 $-5$。若锚点价值为0，则条件价值始终为0。

若条件后的效果全部为正向收益，即 $G^-=\varnothing$，公式简化为：

$$
V(\text{Cond}_T(E_a)+G)
=
\max\left(C(T;E_a)+V(G),0\right)
$$

上下文已明确真实触发事件及其概率时，可以沿用简写：

$$
\text{Cond}(E_a)+G
$$

简写中的 $E_a$ 仍是条件价值代理，不能据此反推真实触发语义或触发概率。

参考概率：

| 条件事件 | $p(E)$ |
|:--|:--|
| 对方召唤怪物 | 0.9 |
| 对方发起预言 | 0.9 |
| 对方发起攻击 | 0.8 |
| 对方使用技能 | 0.8 |
| 对方怪物使用【反应属性】 | 0.3 |
| 对方战斗破坏我方怪物 | 0.5 |
| 对方给我方战斗伤害 | 0.4 |
| 对方给我方效果伤害 | 0.33 |
| 对方效果破坏我方怪物 | 0.2 |
| 对方使用预言卡破坏我方怪物 | 0.1 |

即便事件非常不可能发生，也将 $p(E)$ 提高到最低参考值0.1。条件事件因此会显著拉低整条效果的估值；在相同的设计目标下，反应属性和响应效果可以配置更高的正面效果。

“对方怪物使用【反应属性】”的参考概率 $p(T)=0.3$ 已同时包含以下两层不确定性：

- 对方场上存在拥有【反应属性】的怪物；
- 该怪物的【反应属性】在相关回合内实际满足条件并触发一次。

因此，使用该参考概率估值时，不再为“对方存在拥有【反应属性】的怪物”额外乘一次状态存在概率，以免重复折扣。

例：当我方给对方造成5点以上效果伤害时，我方信仰+10。

$$
T=\text{我方给对方造成至少5点效果伤害},
\qquad
E_a=-\text{DMG.E}(-5),
\qquad
A(E_a)=1
$$

设 $p(T)=0.3$，则：

$$
k(0.3)=\sqrt{\frac{0.7}{0.3}}\approx1.528
$$

$$
V=-1.528\times1+2\approx0.472
$$

例：当我方受到5点以上效果伤害时，我方信仰+10。

$$
T=\text{我方受到至少5点效果伤害},
\qquad
E_a=\text{DMG.E}(-5),
\qquad
A(E_a)=-1
$$

若 $p(T)=0.2$，则 $k(0.2)=2$：

$$
V=-2\times1+2=0
$$

例：当触发概率为0.2的事件发生时，我方信仰-5，并获得一项价值3的正向收益。若条件垫付为 $C=-5$，则：

$$
V(G^-)=-1,\qquad V(G^+)=3
$$

$$
V=0.2\times(-1)+\max(-5+3,0)=-0.2
$$

条件垫付没有把正向收益拉成负数，但真实信仰代价经过触发概率矫正后仍使整条效果为负。

### 2.7 实现系数 $q(E)$

$$
V(E)=P(S_E)\cdot q(E)\cdot B(E)
$$

| 范围 | 含义 |
|:--|:--|
| $0<q<1$ | 效果比理论值更难完全兑现 |
| $q=1$ | 按理论价值兑现，也是默认值 |
| $q>1$ | 检索、精确选择等优势放大效果价值 |

$P(S)$ 与 $q(E)$ 可以同时使用：前者处理起效的必要状态，后者处理效果实际落地的程度。

### 2.8 选择与随机

$$
V(\text{Select}(E_1,E_2,i))=
\begin{cases}
\max(V(E_1),V(E_2)) & i=1\\
\min(V(E_1),V(E_2)) & i=-1
\end{cases}
$$

价值为0的真实分支仍参与选择，例如“可以不发动”是价值为0的选项。只有分支不存在，记作 $\varnothing$，才退化为单一事件。

$$
V(\text{Random}(E_1,\dots,E_n))
=
\frac1n\sum_{k=1}^{n}V(E_k)
$$

未写权重时，`Random` 明确表示各分支等概率。加权形式为：

$$
V\left(
\text{Random}((w_1,E_1),\dots,(w_n,E_n))
\right)
=
\sum_{k=1}^{n}w_kV(E_k)
$$

其中：

$$
w_k\ge0,\qquad \sum_{k=1}^{n}w_k=1
$$

概率未知时，必须由设计者给出估计权重，不能自动按等概率处理。

### 2.9 估值等价

复杂卡效可以分解为价值相近的基础事件：

$$
E_1\equiv_V E_2
\quad\Longleftrightarrow\quad
V(E_1)=V(E_2)
$$

$\equiv_V$ 只表示估值等价，不表示两者在游戏规则、触发事件或连锁关系上相同。

### 2.10 随机变量与非线性节点

若基础价值函数在随机变量 $X$ 的全部取值范围内保持线性，可以直接代入期望：

$$
\mathbb E[B(E(X))]
=
B(E(\mathbb E[X]))
$$

例如：

$$
\mathbb E[B(\text{DMG}(X))]
=
0.2\mathbb E[X]
$$

遇到以下非线性情况时，不能先把 $X$ 替换为期望：

- `max/min`；
- `Select`；
- 吉姆函数跨越正负参数区间；
- $\text{HC}$ 跨越抽牌与弃牌区间；
- 阈值、上限、下限或取整。

此时必须先按每个结果估值，再求期望：

$$
\mathbb E[V(E(X))]
=
\sum_xP(X=x)V(E(x))
$$

例如，$X$ 有一半概率表示抽1张牌，另一半概率表示弃1张牌。不能使用 $\text{HC}(\mathbb E[X])=\text{HC}(0)$，而应计算：

$$
\frac12B(\text{HC}(1))
+
\frac12B(\text{HC}(-1))
=
\frac12-\frac14
=
0.25
$$

---

## 3. 按效果类型分析

### 3.1 伤害与信仰

$$
B(\text{DMG}(x))
=
B(\text{DMG.E}(x))
=
B(\text{DMG.A}(x))
=
0.2x
$$

$x>0$ 表示恢复，$x<0$ 表示受到伤害。

例：

$$
B(\text{DMG}(5))=1
$$

$$
B(-\text{DMG.E}(-5))=1
$$

### 3.2 灵力

| 事件 | 基础理论价值 | 分析 |
|:--|:--|:--|
| $\text{MANA}(i,j,x)$ | $v_{1,0.5}(i,j,x)$ | 包含玩家与目标选择 |
| $\text{MANA.rand}(j,x)$ | $0.8jx$ | $j$ 方无玩家自由选择目标的总等效灵力变化 |
| $\text{MANA.rand}(x)$ | $0.8x$ | $\text{MANA.rand}(1,x)$ 的短写 |
| $\text{MANA.self}(x)$ | $0.9x$ | 无自由分配 |
| $\text{MANA.each}(j,x)$ | $1.5jx$ | $j$ 方全体怪物，按 $n_{\text{monster}}=1.5$ 个对象估计 |
| $\text{MANA.each}(x)$ | $1.5x$ | $\text{MANA.each}(1,x)$ 的短写 |
| $\text{MANA.discount.next}(A,x)$ | $x$ | 下一次执行行动 $A$ 时节省 $x$ 点灵力 |

例：

$$
B(\text{MANA}(1,1,2))=2
$$

### 3.3 攻击与防御

| 事件 | 基础理论价值 | 分析 |
|:--|:--|:--|
| $\text{V.ATK}(i,j,x),\text{V.DEF}(i,j,x)$ | $v_{0.2,0.5}(i,j,x)$ | 本回合或下次 |
| $\text{V.ATK.self}(x),\text{V.DEF.self}(x)$ | $0.18x$ | 自身目标 |
| $\text{V.ATK.once}(i,j,x),\text{V.DEF.once}(i,j,x)$ | $v_{0.16,0.5}(i,j,x)$ | 单次即刻 |
| $\text{V.ATK.self.once}(x),\text{V.DEF.self.once}(x)$ | $0.16x$ | 单次即刻且仅自身 |
| $\text{V.ATK.lock}(x),\text{V.DEF.lock}(x)$ | $0.3x$ | 永续增益 |
| $\text{V.ATK.each}(j,x),\text{V.DEF.each}(j,x)$ | $0.3jx$ | $j$ 方所有怪物各变化 $x$，$1.5\times0.2=0.3$ |
| $\text{V.ATK.each}(x),\text{V.DEF.each}(x)$ | $0.3x$ | 默认作用于我方全体怪物 |

例：

$$
B(\text{V.ATK.self}(5))=0.9
$$

### 3.4 手牌与盖牌

| 事件 | 基础理论价值 |
|:--|:--|
| $\text{HC}(x),\ x>0$ | $x$ |
| $\text{HC}(x),\ x<0$ | $-0.5|x|$ |
| $\text{HC.rand}(x),\ x<0$ | $-|x|$ |
| $\text{HC.M}(x),\text{HC.P}(x)$ | 同 $\text{HC}(x)$ |

盖牌与手牌使用同一套 $\text{HC}$ 价值，但移动盖牌与移动正面场牌不同：盖牌返手编码为 $\text{HC}(-1)+\text{HC}(1)$，基础价值为 $-0.5+1=0.5$。必须区分选择方式：对方自选失去一张覆盖预言卡编码为 $-\text{HC.P}(-1)$，价值为 $0.5$；对方随机失去一张则编码为 $-\text{HC.P.rand}(-1)$，价值为 $1$。破坏对方所有覆盖预言卡时同样没有“选择价值最低者”的缓冲，编码为 $-\text{HC.P.rand}(-n_{\text{prophecy}})$；取 $n_{\text{prophecy}}=1.5$，价值为 $1.5$。正面预言卡才使用 $\text{FC.P}$。

例：

$$
B(\text{HC}(-1)+\text{HC}(1))=-0.5+1=0.5
$$

该例是盖1张牌的简化估值。

### 3.5 场牌

| 事件 | 基础理论价值 | 分析 |
|:--|:--|:--|
| $\text{FC}(i,j,1)$ | $v_{3,0.5}(i,j,1)$ | 增加场牌 |
| $\text{FC}(i,j,-1)$ | $v_{3,0.5}(i,j,-1)$ | 减少场牌 |
| $\text{FC.M}(i,j,x)$ | 同 $\text{FC}$ | 目标限定怪物 |
| $\text{FC.P}(i,j,x)$ | 同 $\text{FC}$ | 目标限定预言 |
| $\text{FC.each}(j,x)$ | $9jx$ | $j$ 方所有正面场牌各变化 $x$，按 $n_{\text{field}}=3$ |
| $\text{FC.each}(x)$ | $9x$ | 默认作用于我方全部正面场牌 |
| $\text{FC.M.each}(j,x),\text{FC.P.each}(j,x)$ | $4.5jx$ | 分别按 $n_{\text{monster}}=n_{\text{prophecy}}=1.5$ |

从手牌召唤一只怪物：

$$
B(\text{HC}(-1)+\text{FC.M}(1,1,1))
=
-0.5+3
=
2.5
$$

从牌堆召唤不消耗手牌，并可用 $q(E)=1.25$ 表示检索优势。

### 3.6 行动

| 事件 | 基础理论价值 |
|:--|:--|
| $\text{AK}(i,j,x)$ | $v_{1,0.5}(i,j,x)$ |
| $\text{AK.self}(x)$ | $0.9x$ |
| $\text{AK.each}(j,x)$ | $1.5jx$ |
| $\text{AK.each}(x)$ | $1.5x$ |

例：

$$
B(\text{AK}(1,1,1))=1
$$

### 3.7 查看

| 事件 | 基础理论价值 |
|:--|:--|
| $\text{VIEW.HC}(i,j,x)$ | $0.2ix$ |
| $\text{VIEW.FC}(i,j,x)$ | $0.5ix$ |
| $\text{VIEW.Desk}(i,j,x)$ | $0.1ix$ |
| $\text{VIEW.HC}(x)$ | $0.2x$ |
| $\text{VIEW.FC}(x)$ | $0.5x$ |
| $\text{VIEW.Desk}(x)$ | $0.1x$ |
| $\text{VIEW.HC.all}(i,j)$ | $0.5i$ |
| $\text{VIEW.FC.all}(i,j)$ | $1.25i$ |
| $\text{VIEW.HC.all}$ | $0.5$ |
| $\text{VIEW.FC.all}$ | $1.25$ |

$i$ 决定信息收益属于哪一方，$j$ 记录信息所属方，查看数量 $x\ge0$。查看本来已经公开或已知的信息时，通过 $q(E)$ 将实际价值降低，必要时可取 $q(E)=0$。

例：

$$
B(\text{HC}(2)-\text{VIEW.HC}(1))=2-0.2=1.8
$$

### 3.8 抗性

| 事件 | 基础理论价值 |
|:--|:--|
| $\text{TOL.ATK.player}(x)$ | $0.5x$ |
| $\text{TOL.EFK.player}(x)$ | $0.5x$ |
| $\text{TOL.ATK}(i,j,x)$ | $v_{0.5,0.5}(i,j,x)$ |
| $\text{TOL.EFK}(i,j,x)$ | $v_{0.5,0.5}(i,j,x)$ |
| $\text{TOL.ATK}(x)$ | 同 $\text{TOL.ATK.player}(x)$ |
| $\text{TOL.EFK}(x)$ | 同 $\text{TOL.EFK.player}(x)$ |
| $\text{TOL.ATK.sur.player}(x)$ | $0.4x$ |
| $\text{TOL.EFK.sur.player}(x)$ | $0$ |
| $\text{TOL.ATK.sur}(i,j,x)$ | $v_{0.4,0.5}(i,j,x)$ |
| $\text{TOL.EFK.sur}(i,j,x)$ | $0$ |
| 持续免疫攻击破坏，单回合 | $1.2$ |

例：

$$
B(\text{TOL.ATK.player}(1))=0.5
$$

### 3.9 消除

`CLEAN.M` 只计算怪物的【属性】【反应属性】【技能】三类能力；【增益】不计入 `CLEAN.M`。同一目标仅消除其中一类时取 $n=1$，同时消除两类或三类时统一弱化为 $n=1.5$，不得按类别数线性累加。

`CLEAN.P` 只计算预言卡的有效效果数量，不使用怪物能力类别弱化表。新效果码必须区分 `CLEAN.M` 与 `CLEAN.P`，不得继续使用通用 `CLEAN`。两类永久消除均在等效数量的基础上应用1.5倍系数。

下表中的 $X$ 表示 $\text{CLEAN.M}$ 或 $\text{CLEAN.P}$。

| 事件 | 基础理论价值 |
|:--|:--|
| $\text{CLEAN.M}(i,j,x)$ | $v_{0.5,0.5}(i,j,x)$ |
| $\text{CLEAN.P}(i,j,x)$ | $v_{1.5,0.5}(i,j,x)$ |
| $\text{CLEAN.M.const}(i,j,x)$ | $1.5v_{0.5,0.5}(i,j,x)$ |
| $\text{CLEAN.P.const}(i,j,x)$ | $1.5v_{1.5,0.5}(i,j,x)$ |
| $\text{CLEAN.M}(n),\text{CLEAN.P}(n)$ | 对应 $B(X(1,-1,-n))$ |
| $\text{CLEAN.M.const}(n),\text{CLEAN.P.const}(n)$ | 对应 $B(X.\text{const}(1,-1,-n))$ |
| $\text{CLEAN.M.each}(n)$ | $0.75n$ |
| $\text{CLEAN.P.each}(n)$ | $2.25n$ |
| $\text{CLEAN.M.each.const}(n)$ | $1.125n$ |
| $\text{CLEAN.P.each.const}(n)$ | $3.375n$ |

例：

$$
B(\text{CLEAN.M}(1,-1,-1))
=0.5
$$

$$
B(\text{CLEAN.P}(1,-1,-1))=1.5
$$

### 3.10 检索

| 事件 | 基础理论价值 |
|:--|:--|
| $\text{CALL}$ | $1$ |
| $\text{CALL.M}$ | $1$ |

---

## 4. 计算速查表

下表用于完成常见效果的第一轮计算。专门条目优先于通用后缀。

| 效果码 | $B(E)$ |
|:--|:--|
| $\text{DMG}(x),\text{DMG.E}(x),\text{DMG.A}(x)$ | $0.2x$ |
| $\text{HC}(x),\ x>0$ | $x$ |
| $\text{HC}(x),\ x<0$ | $-0.5|x|$ |
| $\text{HC.rand}(x),\ x<0$ | $-|x|$ |
| $\text{MANA}(i,j,x)$ | $v_{1,0.5}(i,j,x)$ |
| $\text{MANA.self}(x)$ | $0.9x$ |
| $\text{MANA.rand}(j,x)$ | $0.8jx$ |
| $\text{MANA.rand}(x)$ | $0.8x$ |
| $\text{MANA.each}(j,x)$ | $1.5jx$ |
| $\text{MANA.each}(x)$ | $1.5x$ |
| $\text{MANA.discount.next}(A,x)$ | $x$ |
| $\text{V.ATK}(i,j,x),\text{V.DEF}(i,j,x)$ | $v_{0.2,0.5}(i,j,x)$ |
| $\text{V.ATK.self}(x),\text{V.DEF.self}(x)$ | $0.18x$ |
| $\text{V.ATK.once}(i,j,x),\text{V.DEF.once}(i,j,x)$ | $v_{0.16,0.5}(i,j,x)$ |
| $\text{V.ATK.lock}(x),\text{V.DEF.lock}(x)$ | $0.3x$ |
| $\text{V.ATK.rand}(j,x),\text{V.DEF.rand}(j,x)$ | $0.16jx$ |
| $\text{V.ATK.each}(j,x),\text{V.DEF.each}(j,x)$ | $0.3jx$ |
| $\text{V.ATK.each}(x),\text{V.DEF.each}(x)$ | $0.3x$ |
| $\text{FC}(i,j,x),\text{FC.M}(i,j,x),\text{FC.P}(i,j,x)$ | $v_{3,0.5}(i,j,x)$ |
| $\text{FC.rand}(j,x)$ | $2.4jx$ |
| $\text{FC.rand}(x)$ | $2.4x$ |
| $\text{FC.each}(j,x)$ | $9jx$ |
| $\text{FC.each}(x)$ | $9x$ |
| $\text{FC.M.each}(j,x),\text{FC.P.each}(j,x)$ | $4.5jx$ |
| $\text{AK}(i,j,x)$ | $v_{1,0.5}(i,j,x)$ |
| $\text{AK.self}(x)$ | $0.9x$ |
| $\text{AK.rand}(j,x)$ | $0.8jx$ |
| $\text{AK.each}(j,x)$ | $1.5jx$ |
| $\text{VIEW.HC}(i,j,x)$ | $0.2ix$ |
| $\text{VIEW.FC}(i,j,x)$ | $0.5ix$ |
| $\text{VIEW.Desk}(i,j,x)$ | $0.1ix$ |
| $\text{VIEW.HC}(x),\text{VIEW.FC}(x),\text{VIEW.Desk}(x)$ | 分别为 $0.2x,0.5x,0.1x$ |
| $\text{VIEW.HC.all}(i,j)$ | $0.5i$ |
| $\text{VIEW.FC.all}(i,j)$ | $1.25i$ |
| $\text{VIEW.HC.all},\text{VIEW.FC.all}$ | 分别为 $0.5,1.25$ |
| $\text{TOL.ATK.player}(x),\text{TOL.EFK.player}(x)$ | $0.5x$ |
| $\text{TOL.ATK}(i,j,x),\text{TOL.EFK}(i,j,x)$ | $v_{0.5,0.5}(i,j,x)$ |
| $\text{TOL.ATK.sur.player}(x)$ | $0.4x$ |
| $\text{TOL.EFK.sur.player}(x)$ | $0$ |
| $\text{TOL.ATK.sur}(i,j,x)$ | $v_{0.4,0.5}(i,j,x)$ |
| $\text{TOL.EFK.sur}(i,j,x)$ | $0$ |
| $\text{CLEAN.M}(i,j,x)$ | $v_{0.5,0.5}(i,j,x)$ |
| $\text{CLEAN.P}(i,j,x)$ | $v_{1.5,0.5}(i,j,x)$ |
| $\text{CLEAN.M.const}(i,j,x)$ | $1.5v_{0.5,0.5}(i,j,x)$ |
| $\text{CLEAN.P.const}(i,j,x)$ | $1.5v_{1.5,0.5}(i,j,x)$ |
| $\text{CLEAN.M}(n),\text{CLEAN.P}(n)$ | 对应 $B(X(1,-1,-n))$ |
| $\text{CLEAN.M.const}(n),\text{CLEAN.P.const}(n)$ | 对应 $B(X.\text{const}(1,-1,-n))$ |
| $\text{CLEAN.M.rand}(n)$ | $0.4n$ |
| $\text{CLEAN.P.rand}(n)$ | $1.2n$ |
| $\text{CLEAN.M.each}(n)$ | $0.75n$ |
| $\text{CLEAN.P.each}(n)$ | $2.25n$ |
| $\text{CLEAN.M.each.const}(n)$ | $1.125n$ |
| $\text{CLEAN.P.each.const}(n)$ | $3.375n$ |
| $\text{CALL},\text{CALL.M}$ | $1$ |

复合规则：

| 构造器 | $V$ |
|:--|:--|
| $\text{Cond}_\text{has}(S)*E$ | $P(S)q(E)B(E)$ |
| $\text{Cond}_T(E_a)+G$ | 将 $G$ 拆为 $G^++G^-$；$V=p(T)V(G^-)+\max(C(T;E_a)+V(G^+),0)$；$A(E_a)=q_a(E_a)B(E_a)$；$k(p)=\sqrt{(1-p)/p}$；$C=-\min(5,k(p(T))|A(E_a)|)$；$p=0$ 且锚点非零时 $C=-5$，锚点为0时 $C=0$ |
| $\text{Select}(E_1,E_2,1)$ | $\max(V(E_1),V(E_2))$ |
| $\text{Select}(E_1,E_2,-1)$ | $\min(V(E_1),V(E_2))$ |
| $\text{Random}(E_1,\dots,E_n)$ | $\frac1n\sum_kV(E_k)$ |
| $\text{Random}((w_1,E_1),\dots,(w_n,E_n))$ | $\sum_kw_kV(E_k)$，$\sum_kw_k=1$ |

---

## 5. 标准计算流程

1. 将效果码解析为事件树，叶节点为基础事件。
2. 查分类表或速查表，得到各叶节点的基础理论价值 $B(E)$。
3. 对直接事件计算 $V(E)=P(S_E)q(E)B(E)$。
4. 对 `Cond` 节点读取真实触发事件 $T$、条件价值代理 $E_a$、锚点实现系数 $q_a(E_a)$ 和概率 $p(T)$，先计算 $A(E_a)=q_a(E_a)B(E_a)$，再将后续效果拆分为 $G^+$ 与 $G^-$：负向部分按 $p(T)V(G^-)$ 进行概率矫正，正向部分与条件垫付合计后以0为下限；最后与 `Cond_has`、`Select` 和 `Random` 节点一起应用复合规则。
5. 按方向翻转和效果叠加规则自下而上求值。
6. 求和得到整条效果的实际估值 $V_{\text{total}}$。
7. 估值完成后，再结合卡牌费用、等级、使用时机和设计目标判断平衡性；平衡不等同于 $V_{\text{total}}=0$。

---

## 6. 特殊词条与案例

- 【攻击技能】被攻击怪物当次防御-7，使用 $\text{V.DEF.once}(1,-1,-7)$，并加入对方有怪物的状态概率调整。
