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
  const detailTitle = (type, name = '') => type === 'monster_skill' ? `技能${name ? ' - ' + name : ''}` : (effectLabels[type] || type);
  const compactText = (text, limit = 36) => {
    const value = String(text || '').replace(/\s+/g, ' ').trim();
    return value.length > limit ? value.slice(0, limit) + '…' : value;
  };
  window.GemuEffectEditor = Object.freeze({effectLabels, fixedProfessions, professionClasses, supportsEnergy, supportsName, detailTitle, compactText});
})();
