from __future__ import print_function
import numpy as np
from .mmlabpack import *
from .environ import environ
from .logio import logger, add_filehandler, splash

from .database import DatabaseFile, COMPONENT_SEP, groupby_names
continued = {'continued': 1}

__all__ = ['MaterialPointSimulator']

class MaterialPointSimulator(object):
    """The material point simulator

    The material point simulator exercises a material model just as a finite
    element solver would. The steps to creating and running a simulation with
    the `MaterialPointSimulator` are:

    1. Instantiate a `MaterialPointSimulator` simulator object, giving it a
       string `jobid`
    2. Assign a material model to the simulator
    3. Add simulation (deformation) steps to the simulator
    4. Run the simulator

    Output is written to an ExodusII database file. ExodusII database files can
    be viewed using the open source `tsviewer` or `ParaView`.

    Examples
    --------

    In the following simulation, the `ElasticMaterial` is exercised through a
    step of uniaxial strain and then a stress controlled step to bring the
    material to a state of zero stress.

    >>> jobid = 'Job-1'
    >>> mps = MaterialPointSimulator(jobid)
    >>> material = ElasticMaterial(E=10, Nu=.1)
    >>> mps.assign_material(material)
    >>> mps.add_step('EEEEEE', [1., 0., 0., 0., 0., 0.])
    >>> mps.add_step('SSSEEE', [0., 0., 0., 0., 0., 0.])
    >>> mps.run()

    """
    valid_descriptors = ['DE', 'E', 'S', 'DS', 'U', 'F']
    def __init__(self, jobid, initial_temp=0.):
        add_filehandler(logger, jobid+'.log')
        splash(logger)
        logger.info('Matmodlab simulation: {0!r}'.format(jobid))

        self.jobid = jobid
        self.material = None
        self.initial_temp = initial_temp
        logger.info('Initializing the simulation')
        self.init()
        logger.info('Done initializing the simulation')

    def init(self):
        logger.info('Creating initial step... ', extra=continued)
        self.steps = self._initialize_steps(self.initial_temp)
        logger.info('done')

        logger.info('Opening the output database... ', extra=continued)
        self.db = DatabaseFile(self.jobid, 'w')
        logger.info('done')
        logger.info('Output database: {0!r}'.format(self.db.filename))
        self.ran = False
        self._df = None

    def _initialize_steps(self, temp):
        """Create the initial step"""
        begin, end = 0., 0.
        components = np.zeros(6, dtype=np.float64)
        descriptors = ['E'] * 6
        return [Step(0, 0, 0, descriptors, components, temp, 0)]

    def _validate_descriptors(self, descriptors):
        """Validate the user given descriptors"""
        descriptors = list(descriptors)
        for (i, descriptor) in enumerate(descriptors):
            if descriptor.upper() not in self.valid_descriptors:
                raise ValueError('Invalid descriptor {0!r}'.format(descriptor))
            descriptors[i] = descriptor.upper()

        unique_descriptors = list(set(descriptors))
        if 'F' in unique_descriptors:
            if len(unique_descriptors) != 1:
                raise ValueError('Cannot mix F with other descriptors')
            elif len(descriptors) != 9:
                raise ValueError('Must specify all 9 components of F')

        elif 'U' in unique_descriptors:
            if len(unique_descriptors) != 1:
                raise ValueError('Cannot mix U with other descriptors')
            elif len(descriptors) != 3:
                raise ValueError('Must specify all 3 components of U')

        elif np.any(np.in1d(['E', 'S', 'DE', 'DS'], descriptors)):
            if len(descriptors) > 6:
                raise ValueError('At most 6 components of stress/strain '
                                 'can be prescribed')

        return descriptors

    def add_step(self, descriptors, components, increment=1., frames=1,
                 scale=1., kappa=0., temperature=0.):
        """Create a deformation step for the simulation

        Parameters
        ----------
        descriptors : string or listlike of string
            Descriptors for each component of deformation. Each `descriptor` in
            `descriptors` must be one of:
                - `E`: representing strain
                - `DE`: representing an increment in strain
                - `S`: representing stress
                - `DS`: representing an increment in stress
                - `F`: representing the deformation gradient
                - `U`: representing displacement
        components : listlike of reals
            The components of deformation. `components[i]` is interpreted as
            `descriptors[i]`. Thus, `len(components)` must equal
            `len(descriptors)`
        increment : real, optional
            The length of the step in time units, default is 1.
        frames : int, optional
            The number of discrete increments in the step, default is 1
        scale : real or listlike of real
            Scaling factor to be applied to components.  If scale
        kappa : real
            The Seth-Hill parameter of generalized strain.  Default is 0.
        temperature : real
            The temperature at the end of the step.  Default is 0.

        Tensor Component Ordering
        -------------------------
        Component ordering for components is:

        1. Symmetric tensors: XX, YY, ZZ, XY, YZ, XZ
        2. Unsymmetric tensors: XX, XY, XZ YX, YY, YZ ZX, ZY, ZZ
        3. Vectors: X, Y, Z

        Examples
        --------
        To create a step of uniaxial strain with magnitude .1:

        >>> obj.add_step('EEEEEE', [1., 0., 0., 0., 0., 0.], scale=.1)

        To create a step of uniaxial stress with magnitude 1e6:

        >>> obj.add_step('SSSEEE', [1., 0., 0., 0., 0., 0.], scale=1e6)

        Stress and strain (and their increments) can be mixed.  To create a step of uniaxial stress by holding the lateral stress components at 0. and deforming along the axial direction:

        >>> obj.add_step('ESSEEE', [1., 0., 0., 0., 0., 0.], scale=.1)

        To create a step of uniaxial strain, controlled by deformation gradient:

        >>> obj.add_step('FFFFFFFFF', [1.05, 0., 0., 1., 0., 0.], scale=1e6)

        Note, all 9 components of the deformation gradient must be prescribed.

        Special deformation cases are volumetric strain and pressure. Each is
        defined by prescribing one, and only one, component of either strain or
        stress, respectively:

        Volumetric strain.

        >>> obj.add_step('E', .1)

        Pressure:

        >>> obj.add_step('S', 1, scale=1e6)

        Notes
        -----
        Prescribed deformation gradient and displacement components are
        converted to strain. Internally, the driver works only with strain,
        stress, or their increments.

        For stress, strain (and their increments), or mixed steps, all
        components of deformation need not be prescribed (but
        `len(descriptors)` must be equal to `len(components)`). Any missing
        components are assumed to be strain. Accordingly, the following two
        steps would be treated identically:

        >>> obj.add_step('ESSEEE', [1., 0., 0., 0., 0., 0.], scale=.1)
        >>> obj.add_step('ESS', [1., 0., 0.], scale=.1)

        Steps are accumulated by the `MaterialPointSimulator` object and not
        actually run until the `MaterialPointSimulator.run()` method is called.

        """
        if not is_listlike(components):
            components = [components]
        components = np.array(components, dtype=np.float64)

        if is_stringlike(descriptors):
            if len(descriptors) == 1:
                # broadcast descriptor to each component
                descriptors = descriptors * len(components)
            descriptors = list(descriptors)
        if not is_listlike(descriptors):
            raise TypeError('descriptors must be list_like or string_like')
        descriptors = self._validate_descriptors(descriptors)

        if not is_listlike(scale):
            # Scalar scale factor
            scale = np.ones(len(components)) * scale
        scale = np.asarray(scale)

        # Sanity checks
        if len(descriptors) != len(components):
            raise ValueError('components and descriptors must have same length')
        if len(scale) != len(components):
            raise ValueError('components and scale must have same length')

        # Apply scaling factor
        components = components * scale

        if 'F' in descriptors:
            # Convert deformation gradient to strain
            F = np.reshape(components, (3, 3))
            jac = det9(F)
            if jac <= 0:
                raise ValueError('Negative or zero initial Jacobian')

            # convert deformation gradient to strain E with associated
            # rotation given by axis of rotation x and angle of rotation theta
            R, V = np.linalg.qr(F)
            if np.max(np.abs(R - np.eye(3))) > np.finfo(np.float).eps:
                raise ValueError('QR decomposition of deformation gradient '
                                 'gave unexpected rotations (rotations are '
                                 'not yet supported)')
            U = np.dot(R.T, np.dot(V, R))
            components = u2e(U, kappa)
            descriptors = ['E'] * 6

        elif 'U' in descriptors:
            # Convert displacement to strain
            U = np.zeros((3, 3))
            DI3 = np.diag_indices(3)
            U[DI3] = components + 1.
            components = u2e(U, kappa)
            descriptors = ['E'] * 6

        elif 'E' in descriptors and len(descriptors) == 1:
            # only one strain value given -> volumetric strain
            ev = components[0]
            if kappa * ev + 1. < 0.:
                raise ValueError('1 + kappa * ev must be positive')

            if abs(kappa) < np.finfo(np.float).eps:
                eij = ev / 3.
            else:
                eij = ((kappa * ev + 1.) ** (1. / 3.) - 1.)
                eij = eij / kappa
            components = np.array([eij, eij, eij, 0., 0., 0.], dtype=np.float64)
            descriptors = ['E'] * 6

        elif 'S' in descriptors and len(descriptors) == 1:
            # only one stress value given -> pressure
            Sij = -components[0]
            components = np.array([Sij, Sij, Sij, 0., 0., 0.], dtype=np.float64)
            descriptors = ['S'] * 6

        elif 'DS' in descriptors and len(descriptors) == 1:
            # only one stress value given -> pressure
            ds = -components[0]
            components = np.array([ds, ds, ds, 0., 0., 0.], dtype=np.float64)
            descriptors = ['DS', 'DS', 'DS', 'E', 'E', 'E']

        if np.any(np.in1d(['E', 'S', 'DE', 'DS'], descriptors)):
            # Stress/strain must have length == 6
            if len(descriptors) != 6:
                n = 6 - len(descriptors)
                descriptors.extend(['E'] * n)
                components = np.append(components, [0.] * n)

        n = len(self.steps)
        logger.debug('Adding step {0:4d} with descriptors: {1}\n'
                     '                   and components: {2}'.format(
                         n, descriptors, components))

        begin = self.steps[-1].end
        end = begin + increment
        step = Step(begin, end, frames, descriptors, components,
                    temperature, kappa)
        self.steps.append(step)

        return step

    def assign_material(self, material):
        """Assign the material model to the `MaterialPointSimulator`

        Parameters
        ----------
        material : Material
            A material model

        Notes
        -----
        `material` is assumed to be subclassed from the `Material` class.  Accordingly, the following members are assumed to exist:

        - `material.num_sdv`: Number of state dependent variables. Default is
          `None`
        - `material.sdv_names`: Names of state dependent variables (in order
          expected by model). Default is `None`. If `material.num_sdv` is not
          `None` and `material.sdv_names` is `None`, state dependent variables
          are given the names `SDV.1`, `SDV.2`, ..., `SDV.num_sdv`

        The following methods are assumed to exist:

        - `material.sdvini`: Initialize state dependent variables. All state
          dependent variables are assumed to have an initial value of 0. The
          method `sdvini` is used to change this initial value.
        - `material.eval`: The material state update.

        See the documentation for the `Material` base class for more information

        """
        self.material = material

    def reset(self):
        logger.info('Resetting the simulation... ', extra=continued)
        for step in self.steps:
            step.reset()
        self.init()
        logger.info('done')

    def run(self):
        """Run the simulation

        Notes
        -----
        This method initializes and sets up the output database and runs each
        step of the simulation.

        """
        logger.info('Running the simulation')

        if self.material is None:
            raise RuntimeError('Material not assigned')

        if self.ran:
            raise RuntimeError('Already run')

        # Initialize the output database
        logger.info('Initializing the output database... ', extra=continued)
        self.db.initialize(self.get_elem_var_names())
        logger.info('done')

        # Put the initial state in the output database
        step = self.steps[0]
        numx = self.material.num_sdv
        statev = None if numx is None else np.zeros(numx)
        step.statev = self.material.sdvini(statev)
        defgrad = f_from_e(step.kappa, step.strain)
        elem_var_vals = self.astack(step.strain/VOIGT, np.zeros(6),
                                    step.stress, step.stress-np.zeros(6),
                                    defgrad, step.temp, step.statev)
        self.db.save(0, 0, step.end, step.increment, elem_var_vals)
        step.ran = True

        # Run each step
        logger.info('Running each step')
        for i in range(len(self.steps)-1):
            self.run_istep(i+1)
        logger.info('All steps complete')

        self.db.close()
        logger.info('Simulation complete')

        self.ran = True

    @property
    def df(self):
        if not self.ran:
            raise RuntimeError('Must be run before accessing database')
        elif self._df is None:
            self._df = DatabaseFile(self.jobid)
        return self._df

    def get_from_db(self, key):
        """Get `key` from the database

        Parameters
        ----------
        key : str
            key is the name of the variable to get from the database.

        Returns
        -------
        df : DataFrame
            A Pandas DataFrame containing the values for `key` for all times

        Notes
        -----
        `key` can be either:

        - a single component like `F.XX`, in which case a `DataSeries` will be
          returned containing `F.XX` through all time of the simulation
        - a name like `F`, in which case a `DataFrame` will be returned
          containing all of the components of `F` through all time of the
          simulation

        """
        df = self.df
        if key in self.df:
            return self.df[key]
        names_and_cols = groupby_names(self.df.columns)
        if key not in names_and_cols:
            return None
        sep = COMPONENT_SEP
        keys = ['{0}{1}{2}'.format(key, sep, x) for x in names_and_cols[key]]
        return self.df[keys]

    def get2(self, *args):
        return self.df.as_matrix(args)

    def get_elem_var_names(self):
        """Returns the list of element variable names"""
        def expand_var_name(name, components):
            sep = COMPONENT_SEP
            return ['{0}{1}{2}'.format(name, sep, x) for x in components]
        xc1 = ['X', 'Y', 'Z']
        xc2 = ['XX', 'YY', 'ZZ', 'XY', 'YZ', 'XZ']
        xc3 = ['XX', 'XY', 'XZ', 'YX', 'YY', 'YZ', 'ZX', 'ZY', 'ZZ']
        elem_var_names = []
        elem_var_names.extend(expand_var_name('E', xc2))
        elem_var_names.extend(expand_var_name('DE', xc2))
        elem_var_names.extend(expand_var_name('S', xc2))
        elem_var_names.extend(expand_var_name('DS', xc2))
        elem_var_names.extend(expand_var_name('F', xc3))
        elem_var_names.append('Temp')
        if self.material.num_sdv is not None:
            n = self.material.num_sdv
            if self.material.sdv_names is not None:
                assert len(self.material.sdv_names) == n
                elem_var_names.extend(self.material.sdv_names)
            else:
                elem_var_names.extend(expand_var_name('SDV', range(1, n+1)))
        return elem_var_names

    def astack(self, E, DE, S, DS, F, T, XV):
        """Concatenates input arrays into a single flattened array"""
        a = [E, DE, S, DS, F, T, XV]
        return np.hstack(tuple([x for x in a if x is not None]))

    def run_istep(self, istep):
        """Run this step, using the previous step as the initial state

        Parameters
        ----------
        istep : int
            The step number to run

        """
        assert istep != 0
        previous = self.steps[istep-1]
        current = self.steps[istep]
        material = self.material
        assert current.begin == previous.end

        energy = None
        rho = None

        #---------------------------------------------------------------------- #
        # The following variables have values at
        # [begining, end, current] of step
        #---------------------------------------------------------------------- #
        # Time
        time = np.array([current.begin, current.end, current.begin])

        # Temperature
        temp = np.array((previous.temp, current.temp, previous.temp))
        dtemp = (temp[1] - temp[0]) / float(current.frames)


        # Strain and stress states
        strain = np.vstack((previous.strain, current.strain, previous.strain))
        stress = np.vstack((previous.stress, current.stress, previous.stress))

        #---------------------------------------------------------------------- #
        # The following variables have values at
        # [begining, current] of step
        #---------------------------------------------------------------------- #
        if previous.statev is None:
            statev = [None, None]
        else:
            statev = np.vstack((previous.statev, previous.statev))
        F0 = f_from_e(previous.kappa, previous.strain)
        F = np.vstack((F0, F0))

        # v array is an array of integers that contains the rows and columns of
        # the slice needed in the jacobian subroutine.
        nv = 0
        v = np.zeros(6, dtype=np.int)
        for (i, cij) in enumerate(current.components):
            descriptor = current.descriptors[i]
            if descriptor == 'DE':         # -- strain rate
                strain[1, i] = strain[0, i] + cij * VOIGT[i] * current.increment
            elif descriptor == 'E':        # -- strain
                strain[1, i] = cij * VOIGT[i]
            elif descriptor == 'DS':       # -- stress rate
                stress[1, i] = stress[0, i] + cij * current.increment
                v[nv] = i
                nv += 1
            elif descriptor == 'S':        # -- stress
                stress[1, i] = cij
                v[nv] = i
                nv += 1
            else:
                raise ValueError('Invalid descriptor {0!r}'.format(descriptor))

        v = v[:nv]
        vx = [x for x in range(6) if x not in v]
        if current.increment < 1.e-14:
            dedt = np.zeros_like(strain[1])
            dtime = 1.
        else:
            dedt = (strain[1] - strain[0]) / current.increment
            dtime = (time[1] - time[0]) / float(current.frames)

        # --- find current value of d: sym(velocity gradient)
        if not nv:
            # strain or strain rate prescribed and the strain rate is constant
            # over the entire step
            if abs(current.kappa) > 1.e-14:
                d = deps2d(dtime, current.kappa, strain[2], dedt)
            elif environ.SQA:
                d = deps2d(dtime, current.kappa, strain[2], dedt)
                if not np.allclose(d, dedt):
                    logger.warn('SQA: d != dedt')
            else:
                d = np.array(dedt)

        else:
            # Initial guess for d[v]
            dedt[v] = 0.
            #Jsub = J0[[[x] for x in v], v]
            #work = (stress[1,v] - stress[0,v]) / current.increment
            #try:
            #    dedt[v] = solve(Jsub,  work)
            #except:
            #    dedt[v] -= lstsq(Jsub, work)[0]

        # Process each frame of the step
        for iframe in range(current.frames):
            a1 = float(current.frames - (iframe + 1)) / current.frames
            a2 = float(iframe + 1) / current.frames
            strain[2] = a1 * strain[0] + a2 * strain[1]
            pstress = a1 * stress[0] + a2 * stress[1]

            if nv:
                # One or more stresses prescribed
                d = sig2d(self.material, time[2], dtime, temp[2], dtemp,
                          F[0], F[1], strain[2], dedt, stress[2],
                          statev[0], v, pstress[v])

            # compute the current deformation gradient and strain from
            # previous values and the deformation rate
            F[1], e = update_deformation(dtime, current.kappa, F[0], d)
            strain[2,v] = e[v]
            if environ.SQA and not np.allclose(strain[2,vx], e[vx]):
                logger.warn('SQA: bad strain on  step {0}'.format(istep))

            state = material.eval(time[2], dtime, temp[2], dtemp,
                                  F[0], F[1],
                                  np.array(strain[2]), d,
                                  np.array(stress[2]), statev[1])
            s, x, ddsdde = state

            dstress = s - stress[2]
            F[0] = F[1]
            time[2] = a1 * time[0] + a2 * time[1]
            temp[2] = a1 * temp[0] + a2 * temp[1]
            stress[2], statev[1] = s, x
            statev[0] = statev[1]

            elem_var_vals = self.astack(strain[2]/VOIGT, dedt/VOIGT,
                                        stress[2], dstress, F[1], temp[2], x)
            self.db.save(istep+1, iframe+1, time[2], dtime, elem_var_vals)

        current.stress = stress[2]
        current.strain = strain[2]
        current.statev = statev[1]
        current.ran = True

class Step(object):
    def __init__(self, begin, end, frames,
                 descriptors, components, temp, kappa):
        assert len(components) == 6
        assert len(descriptors) == 6
        self.begin = begin
        self.end = end
        self.increment = end - begin
        if abs(self.increment) > 0.:
            assert end > begin
        self.frames = frames
        self.components = np.asarray(components)
        self.descriptors = np.asarray(descriptors)
        self.temp = temp
        self.kappa = kappa

        self.strain = np.where(self.descriptors=='E', self.components, 0.)
        self.stress = np.where(self.descriptors=='S', self.components, 0.)
        self.ran = False

    def reset(self):
        self.strain = np.where(self.descriptors=='E', self.components, 0.)
        self.stress = np.where(self.descriptors=='S', self.components, 0.)
        self.ran = False
