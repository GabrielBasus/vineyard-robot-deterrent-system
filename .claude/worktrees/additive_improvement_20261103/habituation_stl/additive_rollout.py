"""Cell geometry and oracle continuation using the verified additive truth engine.

Planner worlds retain Eq. 20's passive-decay legacy forecast. Oracle worlds
reuse AdditiveGridTruth, including next-step excitation and complete memory.
Neither world can change the live simulator state.
"""
import copy
import math
import numpy as np
from scipy.special import ndtr
from additive_intensity import ADDITIVE_CONTRACT,CellGrid,AdditiveGridTruth
from random_streams import CoupledRandomStreams

def is_additive(L):
    return L.get('truth_process_mode')==ADDITIVE_CONTRACT

def axes(W,H,nx,ny):
    return (np.arange(nx)+.5)*W/nx,(np.arange(ny)+.5)*H/ny

def indices(x,y,W,H,nx,ny):
    return (np.clip(np.floor(np.asarray(y)*ny/H).astype(np.int64),0,ny-1),
            np.clip(np.floor(np.asarray(x)*nx/W).astype(np.int64),0,nx-1))

def mass_kernel(sigma,dx,dy,nx,ny):
    rad=max(nx,ny)-1
    offsets=np.arange(-rad,rad+1)
    px=np.diff(ndtr((np.arange(-rad,rad+2)-.5)*dx/sigma))
    py=np.diff(ndtr((np.arange(-rad,rad+2)-.5)*dy/sigma))
    return rad,np.outer(py,px)

def weight_grids(L,W,H,nx,ny,n_sub):
    xs,ys=axes(W,H,nx,ny);vw=L['value_weight']
    exact=np.array([[vw(float(x),float(y)) for x in xs] for y in ys])
    mean=np.zeros((ny,nx));off=(np.arange(n_sub)+.5)/n_sub-.5
    # Cache by geometry and function object; keep the object alive against id reuse.
    key=(id(vw),W,H,nx,ny,n_sub)
    if key in _WEIGHTS:return _WEIGHTS[key][:2]
    for iy,y in enumerate(ys):
        for ix,x in enumerate(xs):
            mean[iy,ix]=np.mean([vw(float(x+u*W/nx),float(y+v*H/ny)) for u in off for v in off])
    _WEIGHTS[key]=(exact,mean,vw)
    return exact,mean

_WEIGHTS={}

def planner_tree(snap,seed,scenario):
    """Policy-independent proposals for a passive-decay, cell-density forecast.

    Counts use the same left-step quadrature as J, including discrete trigger
    decay. No future branching is introduced into the paper estimator model.
    """
    from habituation_stl import scenario_rollout as sr
    fc=snap.forecast;dt=snap.cfg.dt;n_steps=int(round(snap.horizon_s/dt))
    if fc.legacy_future_offspring:raise ValueError('Additive planner forecast preserves passive decay')
    rng=np.random.default_rng(np.random.SeedSequence([int(seed)&0xffffffff,0x5CE1A410,int(scenario)]))
    area=snap.W*snap.H/(snap.nx*snap.ny)
    ts=[];nodes=[];kinds=[];steps=[]
    trigger=np.zeros_like(fc.bg_node_rate) if fc.legacy_trigger_mass is None else fc.legacy_trigger_mass
    for k in range(1,n_steps+1):
        t=snap.t0+k*dt
        # A replan snapshot has not yet had its t0 model advance. Both entry
        # stages advance the forecast to t0+dt before generating that step.
        for kind,rates in ((0,fc.bg_node_rate*sr.sestpp_time_multiplier(t)*sr._profile_value(fc.bg_time_profile,t)),
                           (3,trigger*math.exp(-max(0,t-(snap.t0 if fc.legacy_state_time is None else fc.legacy_state_time))/fc.omega))):
            counts=rng.poisson(np.maximum(rates.ravel(),0)*area*dt)
            ids=np.repeat(np.arange(counts.size),counts)
            nodes.extend(ids);kinds.extend([kind]*len(ids));steps.extend([k]*len(ids));ts.extend([t]*len(ids))
    node=np.asarray(nodes,dtype=np.int64);n=len(node);iy,ix=np.divmod(node,snap.nx)
    x=(ix+rng.random(n))*snap.W/snap.nx;y=(iy+rng.random(n))*snap.H/snap.ny
    owner=np.full(n,-1,dtype=np.int64)
    for i,r in enumerate(snap.robots):
        if r.zone_polygon:
            inside=sr.points_in_polygon(x,y,r.zone_polygon)&(owner<0);owner[inside]=i
    st=np.asarray(steps,dtype=np.int64)
    return sr._ScenarioTree(t=np.asarray(ts),x=x,y=y,node=node,parent=np.full(n,-1,dtype=np.int64),
        kind=np.asarray(kinds,dtype=np.int64),u_thin=rng.random(n),u_det=rng.random(n),owner=owner,
        w_sched=np.full(n,np.nan),order=np.arange(n),
        step_start=np.searchsorted(st,np.arange(1,n_steps+2)),jitter_seed=int(rng.integers(0,2**31-1)))

class OracleWorld:
    form='additive_truth'
    def __init__(self,snap,recent):
        self.snap=snap;self.recent=recent;fc=snap.forecast
        self.grid=CellGrid(snap.W,snap.H,snap.nx,snap.ny)
        self.engine=AdditiveGridTruth(self.grid,fc.bg_node_rate,branching_mean=fc.alpha,
            sigma=fc.sigma,omega=fc.omega,dt=snap.cfg.dt)
        self.engine.excitation=np.array(fc.truth_excitation_density,copy=True)
        self.J_bg=self.J_exc=self.J_sched=self.counted=0.
        self.streams=None;self.event_tree=None;self.accepted=[]
    def begin_step(self,t):
        from habituation_stl import scenario_rollout as sr
        self.engine.begin_step(t,sr._profile_value(self.snap.forecast.bg_time_profile,t),self.recent)
        self.J_bg+=float(np.sum(np.where(self.snap.region_mask,self.snap.w_bg_node*self.engine.intensity,0)))*self.grid.area*self.snap.cfg.dt
        self.accepted=[]
    def process_events(self,tree,k,t):
        from habituation_stl import scenario_rollout as sr
        if self.streams is None:self.streams=CoupledRandomStreams(tree.jitter_seed)
        proposals=self.engine.proposals(self.streams,k)
        n=len(proposals);owner=np.full(n,-1,dtype=np.int64)
        x=np.array([e[0] for e in proposals]);y=np.array([e[1] for e in proposals])
        for i,r in enumerate(self.snap.robots):
            if r.zone_polygon:
                inside=sr.points_in_polygon(x,y,r.zone_polygon)&(owner<0);owner[inside]=i
        thin=np.array([self.streams.thinning_uniform(e[3]) for e in proposals])
        detect=np.array([self.streams.detection_uniform(e[3],self.snap.robots[int(o)].rid) if o>=0 else 1.
                         for e,o in zip(proposals,owner)])
        iy,ix=indices(x,y,self.snap.W,self.snap.H,self.snap.nx,self.snap.ny)
        node=iy*self.snap.nx+ix
        self.event_tree=sr._ScenarioTree(t=np.full(n,t),x=x,y=y,node=node,parent=np.full(n,-1),
            kind=np.array([0 if e[4]=='background' else 1 for e in proposals]),u_thin=thin,u_det=detect,
            owner=owner,w_sched=np.full(n,np.nan),order=np.arange(n),step_start=np.array([0,n]),jitter_seed=tree.jitter_seed)
        keep=thin<self.engine.probability[iy,ix]
        self.accepted=list(zip(x[keep],y[keep]))
        self.counted+=float(np.sum(self.snap.w_node.ravel()[node[keep]]*self.snap.region_mask.ravel()[node[keep]]))
        return np.flatnonzero(keep)
    def end_step(self):
        if self.engine._open:self.engine.finish_step(self.accepted)
    def on_deterrence_added(self):pass
    def add_legacy_inhibition(self,*args):pass
    def node_exposure_rate(self,t):
        from habituation_stl import scenario_rollout as sr
        background=self.snap.forecast.bg_node_rate*sr._profile_value(self.snap.forecast.bg_time_profile,t)
        inhibition=np.zeros_like(background)
        for e in self.recent:
            if e['t']<=t:
                inhibition+=e['beta']*e.get('eta',1.)*math.exp(-(t-e['t'])/e['omega'])*self.engine.kernel(e['x'],e['y'],e['sigma'])
        return self.snap.w_node*np.maximum(background+self.engine.excitation-inhibition,0)*self.grid.area
    def residual_rate(self,t):return float(np.sum(np.where(self.snap.region_mask,self.node_exposure_rate(t),0)))
    @property
    def J(self):return self.J_bg
