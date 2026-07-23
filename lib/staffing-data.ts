export type Person = { id:string; name:string; initials:string; role:string; location:string; allocation:number; pods:number; specialty:string; availability:string };
export type Request = { id:string; title:string; type:string; owner:string; due:string; hours:number; priority:'High'|'Normal'; status:'Needs recommendation'|'In review'|'Staffed' };

/** Prototype adapter: replace these constants with 26ai DB queries without changing components. */
export const people: Person[] = [
  {id:'P-001',name:'Alex Rivera',initials:'AR',role:'Senior Content Strategist',location:'Austin',allocation:68,pods:3,specialty:'Executive communication',availability:'Available'},
  {id:'P-002',name:'Maya Chen',initials:'MC',role:'Video Producer',location:'Seattle',allocation:84,pods:4,specialty:'Video editing',availability:'Constrained'},
  {id:'P-003',name:'Jordan Lee',initials:'JL',role:'Technical Writer',location:'Denver',allocation:76,pods:3,specialty:'Technical writing',availability:'Available'},
  {id:'P-004',name:'Priya Nair',initials:'PN',role:'Enablement Lead',location:'Bengaluru',allocation:62,pods:2,specialty:'Enablement',availability:'Available'},
  {id:'P-005',name:'Sam Okafor',initials:'SO',role:'Creative Director',location:'London',allocation:71,pods:3,specialty:'Creative writing',availability:'Travel Jul 28–30'},
  {id:'P-006',name:'Elena Garcia',initials:'EG',role:'Communications Manager',location:'Madrid',allocation:48,pods:2,specialty:'Executive communication',availability:'Available'},
  {id:'P-007',name:'Noah Williams',initials:'NW',role:'Video Editor',location:'Chicago',allocation:54,pods:2,specialty:'Video editing',availability:'Available'},
  {id:'P-008',name:'Aisha Patel',initials:'AP',role:'Learning Designer',location:'Atlanta',allocation:39,pods:1,specialty:'Enablement',availability:'Available'}
];
export const requests: Request[] = [
  {id:'REQ-1042',title:'Executive AI adoption video',type:'Communication',owner:'Amy Lawrence',due:'Aug 7',hours:72,priority:'High',status:'Needs recommendation'},
  {id:'REQ-1041',title:'Product launch narrative',type:'Creative writing',owner:'Rohan Shah',due:'Aug 3',hours:48,priority:'High',status:'In review'},
  {id:'REQ-1039',title:'Partner enablement kit',type:'Enablement',owner:'Marta Ruiz',due:'Aug 14',hours:64,priority:'Normal',status:'Staffed'}
];
export const bookings = [
  ['Alex Rivera','Mon','AI campaign messaging','write'],['Alex Rivera','Wed','Customer narrative','blue'],['Maya Chen','Tue','Product launch film','video'],['Maya Chen','Thu','Travel','travel'],['Elena Garcia','Mon','Leadership comms','blue'],['Elena Garcia','Fri','AI adoption video','write'],['Noah Williams','Tue','Video edit review','video'],['Priya Nair','Wed','Partner workshop','enable']
];

export const dataSource = {
  mode: 'excel-prototype' as const,
  workbookPath: '/data/ai-pod-staffing-prototype.xlsx',
  futureDb: { provider: '26ai DB', queryPlaceholder: 'SELECT * FROM staffing.v_staffing_snapshot' },
  async getSnapshot() { return { people, requests, bookings }; }
};
