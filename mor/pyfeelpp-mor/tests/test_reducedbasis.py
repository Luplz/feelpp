import sys
import pytest
import pandas as pd


from feelpp.toolboxes.heat import *
from feelpp.toolboxes.core import *
from feelpp.mor import *
import feelpp

from reducedbasis.reducedbasis import *

sys.argv += ['--config-file', '/home/saigre/feel/thermal-fin/pb4/thermal-fin.cfg']

DIM = 2
assert( DIM in [2,3] )


# Set the environment
o=toolboxes_options("heat")
o.add(makeToolboxMorOptions())
e=feelpp.Environment(sys.argv,opts=o)


# Set the toolboxes
# TODO: get DIM and time_dependent from cfg file
heatBox=heat(dim=DIM,order=1)
heatBox.init()
# model = toolboxmor_2d() if DIM==2 else toolboxmor_3d()
model = toolboxmor(dim=DIM, time_dependent=False)
model.setFunctionSpaces( Vh=heatBox.spaceTemperature())



# Offline computations

def assembleDEIM(mu):
    for i in range(0,mu.size()):
        heatBox.addParameterInModelProperties(mu.parameterName(i),mu(i))
    heatBox.updateParameterValues()
    return heatBox.assembleRhs()

def assembleMDEIM(mu):
    for i in range(0,mu.size()):
        heatBox.addParameterInModelProperties(mu.parameterName(i),mu(i))
    heatBox.updateParameterValues()
    return heatBox.assembleMatrix()

model.setAssembleDEIM(fct=assembleDEIM)
model.setAssembleMDEIM(fct=assembleMDEIM)
model.initModel()

heatBoxDEIM=heat(dim=DIM,order=1)
meshDEIM = model.getDEIMReducedMesh()
heatBoxDEIM.setMesh(meshDEIM)
heatBoxDEIM.init()

def assembleOnlineDEIM(mu):
    for i in range(0,mu.size()):
        heatBoxDEIM.addParameterInModelProperties(mu.parameterName(i),mu(i))
    heatBoxDEIM.updateParameterValues()
    return heatBoxDEIM.assembleRhs()

model.setOnlineAssembleDEIM(assembleOnlineDEIM)

heatBoxMDEIM=heat(dim=DIM,order=1)
meshMDEIM = model.getMDEIMReducedMesh()
heatBoxMDEIM.setMesh(meshMDEIM)
heatBoxMDEIM.init()

def assembleOnlineMDEIM(mu):
    for i in range(0,mu.size()):
        heatBoxMDEIM.addParameterInModelProperties(mu.parameterName(i),mu(i))
    heatBoxMDEIM.updateParameterValues()
    return heatBoxMDEIM.assembleMatrix()

model.setOnlineAssembleMDEIM(assembleOnlineMDEIM)

model.postInitModel()
model.setInitialized(True)
Dmu = model.parameterSpace()


def listOfParams(n):
    mus = []
    for _ in range(n):
        mus.append(Dmu.element(True, True))
    return mus


mubar = Dmu.element(True, False)    # TODO : see how to get the values from json
mubar.setParameters({"Bi":0.1, "k_0":1, "k_1":1, "k_2":1, "k_3":1, "k_4":1})

def alphaLB(mu):
    return min(mu.parameterNamed("k_1"), 1)


@pytest.mark.dependency()
def test_init_environment():
    pytest.decomposition = model.getAffineDecomposition()
    assert(len(pytest.decomposition) == 2)


@pytest.mark.dependency(depends=['test_init_environment'])
def test_init_reducedbasis():

    Aq = pytest.decomposition[0]
    Fq = pytest.decomposition[1]

    pytest.rb = reducedbasis(convertToPetscMat(Aq[0]), convertToPetscVec(Fq[0][0]), model, mubar, alphaLB)



@pytest.mark.dependency(depends=['test_init_reducedbasis'])
def test_computeBasis():
    """Checks that the reduced basis is well computed and orthonormalized
    """
    pytest.mus = listOfParams(40)
    pytest.rb.computeOfflineReducedBasis(pytest.mus, orth=True)
    # assert( rbTest.test_orth() == np.eye(rbTest.N)).all()
    assert( pytest.rb.test_orth() )



@pytest.mark.dependency(depends=['test_computeBasis'])
def test_computeOfflineError():
    """Tests thaht the compute offline error is well run
    """
    pytest.rb.computeOfflineErrorRhs()
    pytest.rb.computeOfflineError()


@pytest.mark.dependency(depends=['test_computeBasis'])
def test_compar():
    """Compare the solutions on the generating sample (should be computer 0)
    """
    for mu in pytest.mus:
        relErrOnU = pytest.rb.compareSols(mu)
        assert( relErrOnU < 1e-12 )


@pytest.mark.dependency(depends=['test_init_environment'])
def test_for_param():
    """check that the error on reduced basis for the generating sample is null, when the basis is not orthonormalized
    """
    Aq = pytest.decomposition[0]
    Fq = pytest.decomposition[1]
    
    rbParam = reducedbasis(convertToPetscMat(Aq[0]), convertToPetscVec(Fq[0][0]), model, mubar, alphaLB)
    # reduced basis only when RB not orthonormilized
    rbParam.computeOfflineReducedBasis(pytest.mus, orth=False)
    for i,mu in enumerate(pytest.mus):
        print('check RB {} with mu:{}'.format(i,mu))
        beta = model.computeBetaQm(mu)
        assert(len(beta) == 2)
        betaA = beta[0]
        betaF = beta[1]
        A = rbParam.assembleA(betaA[0])
        F = rbParam.assembleF(betaF[0][0])

        u,_ = pytest.rb.getSolutionsFE(mu)
        uN = np.array(np.zeros((rbParam.N)))
        uN[i]=1
        AN = rbParam.assembleAN(betaA[0])
        FN = rbParam.assembleFN(betaF[0][0])
        # print('FN:',FN)
        # print("_ NN", "N")
        # print("F", u.dot(F), uN.T @ FN)
        # print("A", u.dot(A * u), uN.T @ AN @ uN)
        assert(abs(u.dot(F) - uN.T @ FN)/abs(u.dot(F)) < 1e-10), "abs(u.dot(F) - uN.T @ FN)/abs(u.dot(F)) = {}".format(abs(u.dot(F) - uN.T @ FN)/abs(u.dot(F)))
        assert(abs(u.dot(A * u) - uN.T @ AN @ uN)/abs(u.dot(A * u)) < 1e-10), "abs(u.dot(A * u) - uN.T @ AN @ uN)/abs(u.dot(A * u)) = {}".format(abs(u.dot(A * u) - uN.T @ AN @ uN)/abs(u.dot(A * u)))


@pytest.mark.dependency(depends=['test_init_reducedbasis'])
def test_comparMatrix():
    """Compares the construction of the matrix to the toolbox one
    """
    mu = Dmu.element(True, False)    # TODO : see how to get the values from json
    mu.setParameters({"Bi":0.01, "k_0":1, "k_1":0.1, "k_2":0.1, "k_3":0.1, "k_4":0.1})
    beta = model.computeBetaQm(mu)
    assert(len(beta) == 2)
    betaA = beta[0]
    # M_tb = heatBox.assembleMatrix().mat()
    M_tb = assembleMDEIM(mu).mat()
    M_tb.assemble()
    M_rb = pytest.rb.assembleA(betaA[0])

    assert(M_tb.size == M_rb.size)
    
    norm = (M_tb - M_rb).norm() / M_tb.norm()
    assert norm < 1e-10, f"relative error {norm} is too high"


@pytest.mark.dependency(depends=['test_init_reducedbasis'])
def test_comparRhs():
    """Compares the construction of the rhs to the toolbox one
    """
    mu = Dmu.element(True, False)    # TODO : see how to get the values from json
    mu.setParameters({"Bi":0.01, "k_0":1, "k_1":0.1, "k_2":0.1, "k_3":0.1, "k_4":0.1})
    beta = model.computeBetaQm(mu)
    assert len(beta) == 2, f"len(beta)={len(beta)} and should be 2"
    betaF = beta[1]
    F_tb = assembleDEIM(mu).vec()
    F_tb.assemble()
    F_rb = pytest.rb.assembleF(betaF[0][0])

    assert F_tb.size == F_rb.size, f"F_tb = {F_tb.size} != {F_rb.size} = F_rb"
    norm = (F_tb-F_rb).norm() / F_tb.norm()
    assert norm < 1e-10, f"relative error {norm} too high"


@pytest.mark.dependency(depends=['test_computeBasis'])
def test_comparSols():
    """Compares the construction of the matrix to the toolbox one
    """
    mu = Dmu.element(True, False)    # TODO : see how to get the values from json
    mu.setParameters({"Bi":0.01, "k_0":1, "k_1":0.1, "k_2":0.1, "k_3":0.1, "k_4":0.1})
    beta = model.computeBetaQm(mu)
    assert(len(beta) == 2)
    betaA = beta[0]
    # M_tb = heatBox.assembleMatrix().mat()
    assembleMDEIM(mu)
    heatBox.solve()
    u_tb = heatBox.fieldTemperature().to_petsc().vec()

    u_rb,_ = pytest.rb.getSolutions(mu)
    u_proj = pytest.rb.projFE(u_rb)

    assert(u_proj.size == u_tb.size)
    
    norm = (u_tb - u_proj).norm() / u_tb.norm()
    assert norm < 1e-10, f"relative error {norm} is too high"


@pytest.mark.dependency(depends=['test_computeBasis'])
def test_comparSolsFE():
    """Compares the construction of the matrix to the toolbox one
    """
    mu = Dmu.element(True, False)    # TODO : see how to get the values from json
    mu.setParameters({"Bi":0.01, "k_0":1, "k_1":0.1, "k_2":0.1, "k_3":0.1, "k_4":0.1})
    beta = model.computeBetaQm(mu)
    assert(len(beta) == 2)
    betaA = beta[0]
    # M_tb = heatBox.assembleMatrix().mat()
    assembleMDEIM(mu)
    heatBox.solve()
    u_tb = heatBox.fieldTemperature().to_petsc().vec()

    u_fe,_ = pytest.rb.getSolutionsFE(mu)

    assert(u_tb.size == u_fe.size)
    
    norm = (u_tb - u_fe).norm() / u_tb.norm()
    assert norm < 1e-10, f"relative error {norm} is too high"



# Greedy Tests

@pytest.mark.long
@pytest.mark.dependency(depends=['test_init_environment'])
def test_runGreedy():
    """runs the greedy algorithm to generate a basis
       (this test is quite long)
    """
    Aq = pytest.decomposition[0]
    Fq = pytest.decomposition[1]
    pytest.rbGreedy = reducedbasis(convertToPetscMat(Aq[0]), convertToPetscVec(Fq[0][0]), model, mubar, alphaLB)

    Xi_train = listOfParams(100)
    mu0 = Dmu.element(True, True)
    S = pytest.rbGreedy.greedy(mu0, Xi_train, Nmax=60)

    assert( pytest.rbGreedy.DeltaMax[-1] < 1e-6 )

# @pytest.mark.greedy
# @pytest.mark.dependency(depends=['test_runGreedy'])
# def test_cvgError(xi_test=None):
#     if xi_test is None:
#         xi_test = listOfParams(50)
#     nb = len(xi_test)

#     df = pd.DataFrame(columns=['minS', 'maxS', 'meanS', 'minU', 'maxU', 'meanU'],
#                       index = list(range(1,pytest.rbGreedy.N+1)))

#     # print("size minS maxS meanS minU maxU meanU")

#     for size in range(1,pytest.rbGreedy.N+1):
#         S = np.zeros(nb)
#         U = np.zeros(nb)

#         for i in range(nb):
#             uN, sN = pytest.rbGreedy.getSolutions(xi_test[i], size=size)
#             u , s  = pytest.rbGreedy.getSolutionsFE(xi_test[i])

#             u_proj = pytest.rbGreedy.projFE(uN)

#             S[i] = np.abs(sN - s)/np.abs(s)
#             U[i] = pytest.rbGreedy.normA(u - u_proj)/pytest.rbGreedy.normA(u)

#         df.loc[size] = pd.Series({'minS':np.min(S), 'maxS':np.max(S), 'meanS':np.mean(S),
#                                   'minU':np.min(U), 'maxU':np.max(U), 'meanU':np.mean(U)})
#         # print(size, np.min(S), np.max(S), np.mean(S), np.min(U), np.max(U), np.mean(U))
#     return df





# Other tests

@pytest.mark.dependency(depends=['test_computeBasis'])
def test_save_load():
    """Tests that the loaded matrices are identical to the ones saved
    """
    os.system("rm -rf /tmp/rb")
    assert( reducedbasis.loadReducedBasis('/tmp/rb', model) == None )

    pytest.rb.saveReducedBasis('/tmp/rb')
    rbLoaded = reducedbasis.loadReducedBasis('/tmp/rb', model)

    assert( pytest.rb.Qa == rbLoaded.Qa )
    assert( pytest.rb.Qf == rbLoaded.Qf )
    assert( pytest.rb.N == rbLoaded.N )

    for q in range(rbLoaded.Qa):
        assert( (pytest.rb.ANq[q] == rbLoaded.ANq[q]).all() ), f"q = {q}"
    for p in range(rbLoaded.Qf):
        assert( (pytest.rb.FNp[p] == rbLoaded.FNp[p]).all() ), f"p = {p}"