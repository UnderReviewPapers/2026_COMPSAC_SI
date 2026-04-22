const customModdle = {
  name: 'custom',
  uri: 'http://example.com/custom',
  prefix: 'custom',
  xml: {
    tagAlias: 'lowerCase'
  },
  types: [
    {
      name: 'AtomicExtension',
      superClass: ['Element'],
      properties: [
        { name: 'atomicType', isAttr: false, type: 'String' },
        { name: 'inputParams', isAttr: false, type: 'String' },
        { name: 'outputParams', isAttr: false, type: 'String' },
        { name: 'method', isAttr: false, type: 'String' },
        { name: 'url', isAttr: false, type: 'String' },
        { name: 'owner', isAttr: false, type: 'String' }
      ]
    },
    {
      name: 'GroupExtension',
      superClass: ['Element'],
      properties: [
        { name: 'groupType', type: 'String' },
        { name: 'name', type: 'String' },
        { name: 'description', type: 'String' },
        { name: 'workflowType', type: 'String' },
        { name: 'members', type: 'String' },
        { name: 'actor', type: 'String' },  
        { name: 'actors', type: 'String' },
        { name: 'gdprMap', type: 'String' },
        { name: 'businessGoal', type: 'String' }
      ]
    }
  ]
};
