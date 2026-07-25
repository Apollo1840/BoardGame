(function () {
  const effectLabels = Object.freeze({
    monster_skill: '怪物技能',
    monster_attribute: '通常属性',
    monster_reactive_attribute: '反应属性',
    prophecy_effect: '预言效果',
    prophecy_reactive_effect: '预言响应效果'
  });
  const fixedProfessions = Object.freeze(['刺客', '坦克', '射手', '法师', '辅助']);
  const professionClasses = Object.freeze({刺客:'profession-assassin',坦克:'profession-tank',射手:'profession-marksman',法师:'profession-mage',辅助:'profession-support'});
  const supportsEnergy = type => type === 'monster_skill';
  const supportsName = type => type === 'monster_skill';
  const effectProfessionGroups = (effects = []) => {
    const primary = new Set();
    const secondary = new Set();
    effects.forEach(effect => {
      let target = null;
      if (effect.type === 'monster_attribute' || (effect.type === 'monster_skill' && (Number(effect.energy_cost) || 0) <= 0) || effect.type === 'prophecy_effect') target = primary;
      else if (effect.type === 'monster_reactive_attribute' || (effect.type === 'monster_skill' && (Number(effect.energy_cost) || 0) > 0) || effect.type === 'prophecy_reactive_effect') target = secondary;
      if (target) (effect.professions || []).forEach(profession => target.add(profession));
    });
    return {primary: [...primary], secondary: [...secondary]};
  };
  const monsterStatProfessions = (level, attack, defence) => {
    const threshold = (Math.max(0, Number(level) || 0) + 1) * 5;
    const professions = [];
    if ((Number(attack) || 0) > threshold) professions.push('刺客');
    if ((Number(defence) || 0) > threshold) professions.push('坦克');
    return professions;
  };
  const cardProfessionGroups = card => {
    const base = card?.base || card || {};
    const groups = effectProfessionGroups(card?.effects || []);
    const primary = new Set(groups.primary);
    if ((card?.type || base.type) === 'monster') {
      monsterStatProfessions(base.level, base.attack, base.defence).forEach(profession => primary.add(profession));
    }
    return {primary: [...primary], secondary: groups.secondary};
  };
  const detailTitle = (type, name = '') => type === 'monster_skill' ? `技能${name ? ' - ' + name : ''}` : (effectLabels[type] || type);
  const compactText = (text, limit = 36) => {
    const value = String(text || '').replace(/\s+/g, ' ').trim();
    return value.length > limit ? value.slice(0, limit) + '…' : value;
  };
  window.GemuEffectEditor = Object.freeze({effectLabels, fixedProfessions, professionClasses, supportsEnergy, supportsName, effectProfessionGroups, monsterStatProfessions, cardProfessionGroups, detailTitle, compactText});
})();
