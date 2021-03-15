import sys
sys.path.append("D:\\DTU\\firstProject\\MissingDataTraining")
from missingDataTrainingModule import *
from datasets import *



from torch.distributions import *
from torch.optim import *
from functools import partial
from lime import lime_image
from skimage.segmentation import mark_boundaries

if __name__ == "__main__":

    dataset = CircleDatasetNotCentered
    lambda_reg = 1.0
    lr = 1e-4
    lambda_reconstruction = 1.0
    nb_epoch=10
    epoch_pretrain = 5

    Nexpectation_train = 10
    Nexpectation_test = 1
    bias_classifier = True
    bias_destructor = True


    imputationMethod = partial(ConstantImputation, cste = 0, add_mask = False)   
    # imputationMethod = ConstantImputation

    noise_function = DropOutNoise(pi = 0.3)
    train_reconstruction = False
    train_postprocess = False
    reconstruction_regularization = None
    post_process_regularization =  None

    if reconstruction_regularization is None and post_process_regularization is None :
        need_autoencoder = False
    else :
        need_autoencoder = True



    folder = "D:\DTU\Interpretable_or_not"
    if not os.path.exists(folder):
        os.makedirs(folder)
    folder = os.path.join(folder,dataset.__name__)
    if not os.path.exists(folder):
        os.makedirs(folder)

    experiment_name = "0_Imputation_lambda_0_1"
    final_path = os.path.join(folder, experiment_name)
    if not os.path.exists(final_path):
        os.makedirs(final_path)

    print(f"Save at {final_path}")

    input_size_destructor = (1,2)
    input_size_autoencoder = (1,2)
    input_size_classifier = (1,2)
    input_size_classification_module = (1,2)

    # feature_extractor = FeatureExtraction().cuda()
    feature_extractor = None

    mnist = LoaderArtificial(dataset)
    data, target= next(iter(mnist.test_loader))
    data = data[:300]
    target = target[:300]
   #============ Autoencoder ===================

    if need_autoencoder :
        autoencoder_network = AutoEncoder(input_size=input_size_autoencoder).cuda()

        mnist_noise = LoaderArtificial(dataset, noisy=True, noise_function=noise_function)
        optim_autoencoder = Adam(autoencoder_network.parameters())
        data_autoencoder, target_autoencoder = next(iter(mnist_noise.test_loader))
        data_autoencoder = data_autoencoder[:4]
        target_autoencoder = target_autoencoder[:4]
        
        
            
        for epoch in range(epoch_pretrain):
            train_autoencoder(autoencoder_network, mnist_noise, optim_autoencoder)
            test_autoencoder(autoencoder_network, mnist_noise)
            autoencoder_network.eval()

                        

   #============ No Variationnal ===============

          
    parameter = {
        "train_reconstruction": train_reconstruction,
        "train_postprocess" : train_postprocess,
        "recons_reg" : reconstruction_regularization,
        "post_process_reg" : post_process_regularization,
        "epoch_pretrain": epoch_pretrain,
        "noise_function":noise_function,
        "lambda_reg":lambda_reg,
        "post_process_regularization":post_process_regularization,
        "reconstruction_regularization":reconstruction_regularization,
        "feature extractor": feature_extractor,
        "nb_epoch" :nb_epoch,
        "N_expectation_train": Nexpectation_train,
        "N_expectation_test" : Nexpectation_test,
    }

 
    if not os.path.exists(final_path):
        os.makedirs(final_path)

    with open(os.path.join(final_path,"class.txt"), "w") as f:
        f.write(str(parameter))

    if need_autoencoder :
        save_interpretation(final_path,
        data_autoencoder.detach().cpu().numpy(), 
        target_autoencoder.detach().cpu().numpy(), [0,1,2,3],prefix= "input_autoencoder")

        autoencoder_network_missing = copy.deepcopy(autoencoder_network)
        output = autoencoder_network_missing(data_autoencoder.cuda()).reshape(data_autoencoder.shape)

        save_interpretation(final_path,
        output.detach().cpu().numpy(), 
        target_autoencoder.detach().cpu().numpy(), [0,1,2,3], prefix="output_autoencoder_before_training")

    ##### ============ Classification training ========= :

    if feature_extractor is not None :
        classifier = ClassifierFromFeature()
    else :
        classifier = StupidClassifier(input_size_classifier, mnist.get_category(), bias=bias_classifier)
    classification_vanilla = ClassificationModule(classifier, feature_extractor=feature_extractor)


    optim_classifier = Adam(classification_vanilla.parameters())
    if feature_extractor is not None :
        optim_feature_extractor = Adam(feature_extractor.parameters())
    else :
        optim_feature_extractor = None
    trainer_vanilla = ordinaryTraining(classification_vanilla, feature_extractor=feature_extractor)



    ##### ============  Missing Data destruc training ===========:

    if feature_extractor is not None :
        destructor_no_var = DestructorFromFeature()
    else :
        destructor_no_var = DestructorSimilar(input_size_destructor, bias = bias_destructor)
    destruction_var = DestructionModule(destructor_no_var, feature_extractor=feature_extractor,
        regularization=free_regularization,
    )
    if post_process_regularization is not None :
        post_proc_regul = post_process_regularization(autoencoder_network_missing, to_train = train_postprocess)
    else :
        post_proc_regul = None
    
    if reconstruction_regularization is not None :
        recons_regul = reconstruction_regularization(autoencoder_network_missing, to_train = train_reconstruction)
    else : recons_regul = None
    

    imputation = imputationMethod(input_size= input_size_classification_module,post_process_regularization = post_proc_regul,
                    reconstruction_reg= recons_regul)
    classification_var = ClassificationModule(classifier, imputation=imputation, feature_extractor=feature_extractor)

    trainer_var = noVariationalTraining(
        classification_var,
        destruction_var,
        feature_extractor=feature_extractor,
    )


    optim_classification = Adam(classification_var.parameters(), lr=lr)
    optim_destruction = Adam(destruction_var.parameters(), lr=lr)
    

    temperature = torch.tensor([1.0])

    if torch.cuda.is_available():
        temperature = temperature.cuda()

    total_dic_train = {}
    total_dic_test_no_var = {}
    for epoch in range(nb_epoch):
        
        dic_train = trainer_var.train(
            epoch, mnist,
            optim_classification, optim_destruction,
            partial(RelaxedBernoulli,temperature),
            optim_feature_extractor= optim_feature_extractor,
            lambda_reg=lambda_reg,
            lambda_reconstruction = lambda_reconstruction,
            save_dic = True,
            Nexpectation=Nexpectation_train
        )
        dic_test_no_var = trainer_var.test_no_var(mnist, partial(RelaxedBernoulli,temperature), Nexpectation=Nexpectation_test)
        temperature *= 0.5

        total_dic_train = fill_dic(total_dic_train, dic_train)
        total_dic_test_no_var = fill_dic(total_dic_test_no_var, dic_test_no_var)

    

    ####### Sample and save results :

    

    save_dic(os.path.join(final_path,"train"), total_dic_train)
    save_dic(os.path.join(final_path,"test_no_var"), total_dic_test_no_var)
    
    pred = trainer_var._predict(data.cuda(), partial(RelaxedBernoulli,temperature), dataset = mnist).detach().cpu().numpy()
    pred = np.argmax(pred, axis = 1)
    z_s = destructor_no_var(data.cuda())
    z_s = z_s.reshape(data.shape)
    data_destructed, _ = classification_var.imputation.impute(data.cuda(), z_s)
    data_destructed = data_destructed.detach().cpu().numpy()
    save_result_artificial(final_path, data, target, pred)
    w = classification_var.classifier.fc1.weight.detach().cpu().numpy()
    b = classification_var.classifier.fc1.bias.detach().cpu().numpy()
    z_s = z_s.detach().cpu().numpy()
    save_interpretation_artificial(final_path, data_destructed, target, pred, w, b)
    print(z_s.shape)
    save_interpretation_artificial_bar(final_path, z_s, target, pred)

   