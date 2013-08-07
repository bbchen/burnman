# BurnMan - a lower mantle toolkit
# Copyright (C) 2012, 2013, Heister, T., Unterborn, C., Rose, I. and Cottaar, S.
# Released under GPL v2 or later.

import os, sys, numpy as np
import matplotlib.pyplot as plt
import scipy.integrate as integrate

import seismic
import tools
import averaging_schemes
from composite import composite

#phase = namedtuple('phase', ['mineral', 'fraction'])

class elastic_properties:
    """
    class that contains volume V [m^3] , density rho [kg/m^3] , 
    bulk_modulus K [Pa], and shear_modulus G [Pa].
    """
    def __init__(self, V=None, rho=None, K=None, G=None, fraction=None):
        self.V = V
        self.rho = rho
        self.K = K
        self.G = G
        self.fraction = fraction

    def set_size(self, size):
        self.V = np.ndarray(size)
        self.rho = np.ndarray(size)
        self.K = np.ndarray(size)
        self.G = np.ndarray(size)
        self.fraction = np.ndarray(size)


def calculate_moduli(rock, pressures, temperatures):
    """
    Given a composite and a list of pressures [Pa] and temperatures [K],
    calculate the elastic moduli and densities of the individual phases.

    Returns: an array of (n_phases by n_evaluation_poins) of elastic_properties() instances
    """
    moduli = [ elastic_properties() for ph in rock.phases ]
    for m in moduli:
        m.set_size(len(pressures))
        
    for idx in range(len(pressures)):
        rock.set_state(pressures[idx], temperatures[idx])
        
        for midx in range(len(moduli)):
            m = moduli[midx]
            ph = rock.phases[midx]
            m.V[idx] = ph.fraction * ph.mineral.molar_volume()
            m.K[idx] = ph.mineral.adiabatic_bulk_modulus()
            m.G[idx] = ph.mineral.shear_modulus()
            m.rho[idx] = ph.mineral.molar_mass() / ph.mineral.molar_volume()
            m.fraction[idx] = ph.fraction
        
    return moduli

def average_moduli(moduli_list, averaging_scheme=averaging_schemes.voigt_reuss_hill):
    """
    Given an array of (n_phases by n_evaluation_points) instances of elastic_properties() 
    (as, for instance, generated by calculate_moduli), calculate the bulk properties,
    according to some averaging scheme.  The averaging scheme defaults to Voigt-Reuss-Hill, 
    but the user may specify, Voigt, Reuss, the Hashin-Shtrikman bounds, 
    or any user defined scheme that satisfies the interface in averaging_schemes.
    
    Returns: a list of n_evaluation_points instances of elastic_properties()
    """
    n_pressures = len(moduli_list[0].V)
    result = elastic_properties()
    result.set_size(n_pressures)
    
    for idx in range(n_pressures):
        fractions = [m.fraction[idx] for m in moduli_list]

        #come up with volume fractions of the phases
        V_ph = [m.V[idx] for m in moduli_list]
        V_mol = np.array(V_ph)*np.array(fractions)
        V_frac = V_mol/sum(V_mol)

        K_ph = [m.K[idx] for m in moduli_list]
        G_ph = [m.G[idx] for m in moduli_list]
        rho_ph = [m.rho[idx] for m in moduli_list]
               
        result.V[idx] = sum(V_mol)
        result.K[idx] = averaging_scheme.average_bulk_moduli(V_frac, K_ph, G_ph)
        result.G[idx] = averaging_scheme.average_shear_moduli(V_frac, K_ph, G_ph)
        result.rho[idx] = averaging_scheme.average_density(V_frac, rho_ph)
        result.fraction[idx] = 1.0

    return result

def compute_velocities(moduli):
    """
    Given a list of elastic_properties, 
    compute the seismic velocities Vp, Vs, and Vphi
    Returns a list: Vp [m/s], Vs [m/s], Vphi [m/s]
    """
    mat_vs = np.ndarray(len(moduli.V))
    mat_vp = np.ndarray(len(moduli.V))
    mat_vphi = np.ndarray(len(moduli.V))
    
    for i in range(len(moduli.V)):

        mat_vs[i] = np.sqrt( moduli.G[i] / moduli.rho[i])
        mat_vp[i] = np.sqrt( (moduli.K[i] + 4./3.*moduli.G[i]) / moduli.rho[i])
        mat_vphi[i] = np.sqrt( moduli.K[i] / moduli.rho[i])
    
    return mat_vp, mat_vs, mat_vphi
 
 
def velocities_from_rock(rock, pressures, temperatures, averaging_scheme=averaging_schemes.voigt_reuss_hill()):
    """
    A function that rolls several steps into one:  given a rock and a list of pressures and temperatures,
    it calculates the elastic moduli of the individual phases using calculate_moduli(), averages them using
    average_moduli(), and calculates the seismic velocities using compute_velocities().

    Returns a big list: density [kg/m^3], Vp [m/s], Vs [m/s], Vphi [m/s], K [m/s], G [m/s]
    """
    moduli_list = calculate_moduli(rock, pressures, temperatures)
    moduli = average_moduli(moduli_list, averaging_scheme)
    mat_vp, mat_vs, mat_vphi = compute_velocities(moduli)
    return moduli.rho, mat_vp, mat_vs, mat_vphi, moduli.K, moduli.G



def apply_attenuation_correction(v_p,v_s,v_phi,Qs,Qphi):
    """
    Returns lists of corrected Vp Vs and Vphi for a given Qs and Qphi
    """
    length = len(v_p)
    ret_v_p = np.zeros(length)
    ret_v_s = np.zeros(length)
    ret_v_phi = np.zeros(length)
    for i in range(length):
        ret_v_p[i],ret_v_s[i],ret_v_phi[i] = \
            seismic.attenuation_correction(v_p[i], v_s[i], v_phi[i],Qs,Qphi)
    
    return ret_v_p, ret_v_s, ret_v_phi


def compare_l2(depth,mat_vs,mat_vphi,mat_rho,seis_vs,seis_vphi,seis_rho):
    """
    It computes the L2 norm for three profiles at a time (assumed to be linear between points).
    Input list of depths, three computed profiles, and three profiles to compare to.
    """
    rho_err_tot = l2(depth,mat_rho,seis_rho)
    vphi_err_tot = l2(depth,mat_vphi,seis_vphi)
    vs_err_tot = l2(depth,mat_vs,seis_vs)
    err_tot=rho_err_tot+vphi_err_tot+vs_err_tot

    return rho_err_tot, vphi_err_tot, vs_err_tot

def compare_chifactor(mat_vs,mat_vphi,mat_rho,seis_vs,seis_vphi,seis_rho):
    """
    It computes the chifactor for three profiles at a time
    """
    rho_err_tot = chi_factor(mat_rho,seis_rho)
    vphi_err_tot = chi_factor(mat_vphi,seis_vphi)
    vs_err_tot = chi_factor(mat_vs,seis_vs)
    err_tot=rho_err_tot+vphi_err_tot+vs_err_tot

    return rho_err_tot, vphi_err_tot, vs_err_tot

def l2(x,funca,funcb):
    """ L2 norm """
    diff=np.array(funca-funcb)
    diff=diff*diff
    length=x[-1]-x[0]
    assert(length>0)
    return integrate.trapz(diff,x) / length
    

def chi_factor(calc,obs):
    #assuming 1% a priori uncertainty on the seismic model

    err=np.empty_like(calc)
    for i in range(len(calc)):
        err[i]=pow((calc[i]-obs[i])/(0.01*np.mean(obs)),2.)

    err_tot=np.sum(err)/len(err)

    return err_tot
